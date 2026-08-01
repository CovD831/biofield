from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .contracts import FeedbackDisposition
from .resources import fixture_root


class EvidenceTaskError(ValueError):
    """Raised when an R1 fixture or submitted answer violates its contract."""


def _fixture_root() -> Path:
    return fixture_root() / "r1"


def _safe_segment(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
        or Path(value).is_absolute()
    ):
        raise EvidenceTaskError(f"{field_name} must be a safe path segment")
    return value


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceTaskError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EvidenceTaskError(f"{field_name} must be an array")
    result = tuple(_text(item, field_name) for item in value)
    if len(set(result)) != len(result):
        raise EvidenceTaskError(f"{field_name} contains duplicate values")
    return result


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceTaskError(f"fixture not found: {path.name}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceTaskError(f"fixture is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise EvidenceTaskError(f"fixture root must be a JSON object: {path}")
    return value


@dataclass(frozen=True)
class EvidenceMaterial:
    material_id: str
    title: str
    text: str

    def __post_init__(self) -> None:
        _text(self.material_id, "material_id")
        _text(self.title, "material title")
        _text(self.text, "material text")

    def to_dict(self) -> dict[str, str]:
        return {
            "material_id": self.material_id,
            "title": self.title,
            "text": self.text,
        }


@dataclass(frozen=True)
class EvidenceTask:
    task_id: str
    task_version: str
    answer_key_version: str
    title: str
    prompt: str
    cross_material_required: bool
    single_agent_has_all_materials: bool
    fact_value_contracts: Mapping[str, Mapping[str, Any]]
    materials: tuple[EvidenceMaterial, ...]
    answer_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "materials", tuple(self.materials))
        object.__setattr__(self, "answer_schema", dict(self.answer_schema))
        if not isinstance(self.fact_value_contracts, Mapping):
            raise EvidenceTaskError("fact_value_contracts must be an object")
        normalized_contracts: dict[str, dict[str, Any]] = {}
        for fact_id, schema in self.fact_value_contracts.items():
            _text(fact_id, "fact contract ID")
            if not isinstance(schema, Mapping):
                raise EvidenceTaskError("fact value contracts must be JSON schemas")
            normalized_schema = dict(schema)
            try:
                Draft202012Validator.check_schema(normalized_schema)
            except SchemaError as error:
                raise EvidenceTaskError(
                    f"fact value contract for {fact_id!r} is invalid"
                ) from error
            if normalized_schema.get("type") != "string":
                raise EvidenceTaskError("fact value contracts must describe strings")
            normalized_contracts[fact_id] = normalized_schema
        if not normalized_contracts:
            raise EvidenceTaskError("fact_value_contracts cannot be empty")
        object.__setattr__(self, "fact_value_contracts", normalized_contracts)
        _text(self.task_id, "task_id")
        _text(self.task_version, "task_version")
        _text(self.answer_key_version, "answer_key_version")
        _text(self.title, "title")
        _text(self.prompt, "prompt")
        if self.cross_material_required is not True:
            raise EvidenceTaskError("R1 tasks must require cross-material reasoning")
        if self.single_agent_has_all_materials is not True:
            raise EvidenceTaskError("R1 tasks must expose every material to one agent")
        if not 3 <= len(self.materials) <= 5:
            raise EvidenceTaskError("R1 tasks must contain 3 to 5 materials")
        if not all(isinstance(item, EvidenceMaterial) for item in self.materials):
            raise EvidenceTaskError("materials must contain EvidenceMaterial values")
        material_ids = tuple(item.material_id for item in self.materials)
        if len(set(material_ids)) != len(material_ids):
            raise EvidenceTaskError("material IDs must be unique")
        if self.answer_schema.get("type") != "object":
            raise EvidenceTaskError("answer_schema must describe an object")
        required = self.answer_schema.get("required")
        if not isinstance(required, list) or not {
            "decision",
            "key_facts",
            "contradictions",
        }.issubset(required):
            raise EvidenceTaskError("answer_schema is missing required output fields")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_version": self.task_version,
            "answer_key_version": self.answer_key_version,
            "title": self.title,
            "prompt": self.prompt,
            "cross_material_required": self.cross_material_required,
            "single_agent_has_all_materials": self.single_agent_has_all_materials,
            "fact_value_contracts": {
                fact_id: dict(schema)
                for fact_id, schema in self.fact_value_contracts.items()
            },
            "materials": [item.to_dict() for item in self.materials],
            "answer_schema": dict(self.answer_schema),
        }


@dataclass(frozen=True)
class ExpectedFact:
    fact_id: str
    accepted_values: tuple[str, ...]
    supporting_material_ids: tuple[str, ...]
    minimum_citations: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_values", tuple(self.accepted_values))
        object.__setattr__(
            self, "supporting_material_ids", tuple(self.supporting_material_ids)
        )
        _text(self.fact_id, "fact_id")
        if not self.accepted_values or any(
            not isinstance(item, str) or not item.strip()
            for item in self.accepted_values
        ):
            raise EvidenceTaskError("accepted_values must contain text values")
        if len(set(self.accepted_values)) != len(self.accepted_values):
            raise EvidenceTaskError("accepted_values must be unique")
        if not self.supporting_material_ids:
            raise EvidenceTaskError("a fact must reference supporting material")
        if len(set(self.supporting_material_ids)) != len(
            self.supporting_material_ids
        ):
            raise EvidenceTaskError("supporting material IDs must be unique")
        if (
            isinstance(self.minimum_citations, bool)
            or not isinstance(self.minimum_citations, int)
            or not 1
            <= self.minimum_citations
            <= len(self.supporting_material_ids)
        ):
            raise EvidenceTaskError("minimum_citations is outside the support set")


@dataclass(frozen=True)
class ExpectedContradiction:
    contradiction_id: str
    material_ids: tuple[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_ids", tuple(self.material_ids))
        _text(self.contradiction_id, "contradiction_id")
        if len(self.material_ids) != 2 or len(set(self.material_ids)) != 2:
            raise EvidenceTaskError(
                "a contradiction must reference two distinct materials"
            )
        for material_id in self.material_ids:
            _text(material_id, "contradiction material_id")


@dataclass(frozen=True)
class EvidenceAnswerKey:
    task_id: str
    task_version: str
    answer_key_version: str
    decision: str
    key_facts: tuple[ExpectedFact, ...]
    contradictions: tuple[ExpectedContradiction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_facts", tuple(self.key_facts))
        object.__setattr__(self, "contradictions", tuple(self.contradictions))
        _text(self.task_id, "answer key task_id")
        _text(self.task_version, "answer key task_version")
        _text(self.answer_key_version, "answer_key_version")
        _text(self.decision, "decision")
        if not self.key_facts:
            raise EvidenceTaskError("answer key must contain critical facts")
        if not self.contradictions:
            raise EvidenceTaskError("answer key must contain a contradiction")
        fact_ids = tuple(item.fact_id for item in self.key_facts)
        contradiction_ids = tuple(
            item.contradiction_id for item in self.contradictions
        )
        if len(set(fact_ids)) != len(fact_ids):
            raise EvidenceTaskError("fact IDs must be unique")
        if len(set(contradiction_ids)) != len(contradiction_ids):
            raise EvidenceTaskError("contradiction IDs must be unique")


@dataclass(frozen=True)
class EvidenceTaskBundle:
    task: EvidenceTask
    answer_key: EvidenceAnswerKey

    def __post_init__(self) -> None:
        if (
            self.task.task_id != self.answer_key.task_id
            or self.task.task_version != self.answer_key.task_version
            or self.task.answer_key_version != self.answer_key.answer_key_version
        ):
            raise EvidenceTaskError("task and answer key versions do not match")
        known_materials = {item.material_id for item in self.task.materials}
        for fact in self.answer_key.key_facts:
            if not set(fact.supporting_material_ids) <= known_materials:
                raise EvidenceTaskError("answer key fact references unknown material")
        for contradiction in self.answer_key.contradictions:
            if not set(contradiction.material_ids) <= known_materials:
                raise EvidenceTaskError(
                    "answer key contradiction references unknown material"
                )
        if not any(fact.minimum_citations >= 2 for fact in self.answer_key.key_facts):
            raise EvidenceTaskError(
                "answer key must contain a cross-material critical fact"
            )
        fact_ids = {fact.fact_id for fact in self.answer_key.key_facts}
        if set(self.task.fact_value_contracts) != fact_ids:
            raise EvidenceTaskError(
                "fact_value_contracts must exactly cover answer key fact IDs"
            )
        for fact in self.answer_key.key_facts:
            validator = Draft202012Validator(
                dict(self.task.fact_value_contracts[fact.fact_id])
            )
            for accepted_value in fact.accepted_values:
                try:
                    validator.validate(accepted_value)
                except ValidationError as error:
                    raise EvidenceTaskError(
                        f"accepted value for {fact.fact_id!r} violates its public contract"
                    ) from error


_F0_VERIFIER_SPEC = {
    "verifier_id": "biofield.evidence_task.f0_requirement_disposition",
    "verifier_version": "1",
    "requirements": {
        "fact_extraction": (
            "critical_fact_score == 1.0",
            "citation_score == 1.0",
        ),
        "contradiction_resolution": ("contradiction_score == 1.0",),
        "decision_synthesis": ("decision_score == 1.0",),
    },
}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _answer_key_contract(bundle: EvidenceTaskBundle) -> dict[str, Any]:
    key = bundle.answer_key
    return {
        "task_id": key.task_id,
        "task_version": key.task_version,
        "answer_key_version": key.answer_key_version,
        "decision": key.decision,
        "key_facts": [
            {
                "fact_id": fact.fact_id,
                "accepted_values": list(fact.accepted_values),
                "supporting_material_ids": list(fact.supporting_material_ids),
                "minimum_citations": fact.minimum_citations,
            }
            for fact in key.key_facts
        ],
        "contradictions": [
            {
                "contradiction_id": contradiction.contradiction_id,
                "material_ids": list(contradiction.material_ids),
            }
            for contradiction in key.contradictions
        ],
    }


def f0_verifier_binding(bundle: EvidenceTaskBundle) -> dict[str, str]:
    """Return fixture and verifier identities/hashes without exposing gold data."""

    if not isinstance(bundle, EvidenceTaskBundle):
        raise TypeError("bundle must be an EvidenceTaskBundle")
    return {
        "fixture_namespace": "biofield.fixtures.r1",
        "task_id": bundle.task.task_id,
        "task_version": bundle.task.task_version,
        "answer_key_version": bundle.answer_key.answer_key_version,
        "task_contract_sha256": _canonical_sha256(bundle.task.to_dict()),
        "answer_key_contract_sha256": _canonical_sha256(
            _answer_key_contract(bundle)
        ),
        "verifier_id": str(_F0_VERIFIER_SPEC["verifier_id"]),
        "verifier_version": str(_F0_VERIFIER_SPEC["verifier_version"]),
        "verifier_contract_sha256": _canonical_sha256(_F0_VERIFIER_SPEC),
    }


@dataclass(frozen=True)
class EvidenceScore:
    critical_fact_score: float
    citation_score: float
    contradiction_score: float
    decision_score: float
    total_score: float
    matched_fact_ids: tuple[str, ...]
    matched_contradiction_ids: tuple[str, ...]
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical_fact_score": self.critical_fact_score,
            "citation_score": self.citation_score,
            "contradiction_score": self.contradiction_score,
            "decision_score": self.decision_score,
            "total_score": self.total_score,
            "matched_fact_ids": list(self.matched_fact_ids),
            "matched_contradiction_ids": list(self.matched_contradiction_ids),
            "issues": list(self.issues),
        }


def available_task_ids(fixture_root: str | Path | None = None) -> tuple[str, ...]:
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    if not root.is_dir():
        raise EvidenceTaskError(f"fixture root not found: {root}")
    return tuple(
        sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and (path / "task.v1.json").is_file()
        )
    )


def load_task_bundle(
    task_id: str,
    *,
    task_version: str = "1",
    answer_key_version: str | None = None,
    fixture_root: str | Path | None = None,
) -> EvidenceTaskBundle:
    safe_task_id = _safe_segment(task_id, "task_id")
    safe_task_version = _safe_segment(task_version, "task_version")
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    task_data = _read_object(
        root / safe_task_id / f"task.v{safe_task_version}.json"
    )
    task = _parse_task(task_data)
    if task.task_id != safe_task_id or task.task_version != safe_task_version:
        raise EvidenceTaskError("task file identity does not match its path")

    selected_key_version = answer_key_version or task.answer_key_version
    safe_key_version = _safe_segment(selected_key_version, "answer_key_version")
    key_data = _read_object(
        root / safe_task_id / f"answer_key.v{safe_key_version}.json"
    )
    answer_key = _parse_answer_key(key_data)
    return EvidenceTaskBundle(task=task, answer_key=answer_key)


def _parse_task(data: Mapping[str, Any]) -> EvidenceTask:
    materials_data = data.get("materials")
    if not isinstance(materials_data, list):
        raise EvidenceTaskError("materials must be an array")
    materials: list[EvidenceMaterial] = []
    for item in materials_data:
        if not isinstance(item, Mapping):
            raise EvidenceTaskError("each material must be an object")
        materials.append(
            EvidenceMaterial(
                material_id=_text(item.get("material_id"), "material_id"),
                title=_text(item.get("title"), "material title"),
                text=_text(item.get("text"), "material text"),
            )
        )
    answer_schema = data.get("answer_schema")
    if not isinstance(answer_schema, Mapping):
        raise EvidenceTaskError("answer_schema must be an object")
    fact_value_contracts = data.get("fact_value_contracts")
    if not isinstance(fact_value_contracts, Mapping):
        raise EvidenceTaskError("fact_value_contracts must be an object")
    return EvidenceTask(
        task_id=_text(data.get("task_id"), "task_id"),
        task_version=_text(data.get("task_version"), "task_version"),
        answer_key_version=_text(
            data.get("answer_key_version"), "answer_key_version"
        ),
        title=_text(data.get("title"), "title"),
        prompt=_text(data.get("prompt"), "prompt"),
        cross_material_required=data.get("cross_material_required"),
        single_agent_has_all_materials=data.get(
            "single_agent_has_all_materials"
        ),
        fact_value_contracts={
            str(fact_id): dict(schema) if isinstance(schema, Mapping) else schema
            for fact_id, schema in fact_value_contracts.items()
        },
        materials=tuple(materials),
        answer_schema=dict(answer_schema),
    )


def _parse_answer_key(data: Mapping[str, Any]) -> EvidenceAnswerKey:
    facts_data = data.get("key_facts")
    contradictions_data = data.get("contradictions")
    if not isinstance(facts_data, list):
        raise EvidenceTaskError("key_facts must be an array")
    if not isinstance(contradictions_data, list):
        raise EvidenceTaskError("contradictions must be an array")

    facts: list[ExpectedFact] = []
    for item in facts_data:
        if not isinstance(item, Mapping):
            raise EvidenceTaskError("each key fact must be an object")
        minimum_citations = item.get("minimum_citations")
        facts.append(
            ExpectedFact(
                fact_id=_text(item.get("fact_id"), "fact_id"),
                accepted_values=_string_tuple(
                    item.get("accepted_values"), "accepted_values"
                ),
                supporting_material_ids=_string_tuple(
                    item.get("supporting_material_ids"),
                    "supporting_material_ids",
                ),
                minimum_citations=minimum_citations,
            )
        )

    contradictions: list[ExpectedContradiction] = []
    for item in contradictions_data:
        if not isinstance(item, Mapping):
            raise EvidenceTaskError("each contradiction must be an object")
        material_ids = _string_tuple(item.get("material_ids"), "material_ids")
        contradictions.append(
            ExpectedContradiction(
                contradiction_id=_text(
                    item.get("contradiction_id"), "contradiction_id"
                ),
                material_ids=material_ids,  # type: ignore[arg-type]
            )
        )

    return EvidenceAnswerKey(
        task_id=_text(data.get("task_id"), "answer key task_id"),
        task_version=_text(data.get("task_version"), "answer key task_version"),
        answer_key_version=_text(
            data.get("answer_key_version"), "answer_key_version"
        ),
        decision=_text(data.get("decision"), "decision"),
        key_facts=tuple(facts),
        contradictions=tuple(contradictions),
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def score_answer(
    bundle: EvidenceTaskBundle,
    answer: Mapping[str, Any],
) -> EvidenceScore:
    if not isinstance(bundle, EvidenceTaskBundle):
        raise TypeError("bundle must be an EvidenceTaskBundle")
    if not isinstance(answer, Mapping):
        raise TypeError("answer must be a mapping")

    issues: list[str] = []
    fact_candidates = _candidate_facts(answer.get("key_facts"), issues)
    matched_fact_ids: list[str] = []
    citation_credits: list[float] = []

    for expected in bundle.answer_key.key_facts:
        candidate = fact_candidates.get(expected.fact_id)
        if candidate is None:
            citation_credits.append(0.0)
            continue
        value, citations = candidate
        value_matches = _normalize(value) in {
            _normalize(item) for item in expected.accepted_values
        }
        if not value_matches:
            citation_credits.append(0.0)
            continue
        matched_fact_ids.append(expected.fact_id)
        unique_citations = set(citations)
        valid_citations = unique_citations & set(expected.supporting_material_ids)
        if not unique_citations:
            citation_credits.append(0.0)
            continue
        precision = len(valid_citations) / len(unique_citations)
        coverage = min(
            1.0, len(valid_citations) / expected.minimum_citations
        )
        citation_credits.append((precision + coverage) / 2)

    expected_fact_count = len(bundle.answer_key.key_facts)
    critical_fact_score = len(matched_fact_ids) / expected_fact_count
    citation_score = sum(citation_credits) / expected_fact_count

    candidate_pairs = _candidate_contradictions(
        answer.get("contradictions"), issues
    )
    expected_by_pair = {
        frozenset(item.material_ids): item.contradiction_id
        for item in bundle.answer_key.contradictions
    }
    matched_pairs = set(candidate_pairs) & set(expected_by_pair)
    matched_contradiction_ids = tuple(
        expected_by_pair[pair] for pair in expected_by_pair if pair in matched_pairs
    )
    if candidate_pairs:
        precision = len(matched_pairs) / len(candidate_pairs)
        recall = len(matched_pairs) / len(expected_by_pair)
        contradiction_score = (
            0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        )
    else:
        contradiction_score = 0.0

    decision = answer.get("decision")
    decision_score = float(
        isinstance(decision, str)
        and _normalize(decision) == _normalize(bundle.answer_key.decision)
    )
    total_score = (
        0.40 * critical_fact_score
        + 0.25 * citation_score
        + 0.25 * contradiction_score
        + 0.10 * decision_score
    )
    return EvidenceScore(
        critical_fact_score=round(critical_fact_score, 6),
        citation_score=round(citation_score, 6),
        contradiction_score=round(contradiction_score, 6),
        decision_score=round(decision_score, 6),
        total_score=round(total_score, 6),
        matched_fact_ids=tuple(matched_fact_ids),
        matched_contradiction_ids=matched_contradiction_ids,
        issues=tuple(issues),
    )


def f0_requirement_disposition(
    bundle: EvidenceTaskBundle,
    *,
    requirement_id: str,
    artifact: Mapping[str, Any],
) -> FeedbackDisposition:
    """Apply the frozen F0 requirement-level verifier contract."""

    answer = {
        "decision": artifact.get("decision", ""),
        "key_facts": artifact.get("key_facts", []),
        "contradictions": artifact.get("contradictions", []),
    }
    score = score_answer(bundle, answer)
    accepted = {
        "fact_extraction": score.critical_fact_score == 1.0
        and score.citation_score == 1.0,
        "contradiction_resolution": score.contradiction_score == 1.0,
        "decision_synthesis": score.decision_score == 1.0,
    }.get(requirement_id)
    if accepted is None:
        raise EvidenceTaskError(f"unknown F0 requirement: {requirement_id}")
    return (
        FeedbackDisposition.ACCEPTED
        if accepted
        else FeedbackDisposition.REJECTED
    )


def _candidate_facts(
    value: Any,
    issues: list[str],
) -> dict[str, tuple[str, tuple[str, ...]]]:
    if not isinstance(value, list):
        issues.append("key_facts must be an array")
        return {}
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            issues.append(f"key_facts[{index}] must be an object")
            continue
        fact_id = item.get("fact_id")
        fact_value = item.get("value")
        citations = item.get("citations")
        if not isinstance(fact_id, str) or not fact_id.strip():
            issues.append(f"key_facts[{index}] has no fact_id")
            continue
        if fact_id in result:
            issues.append(f"duplicate fact_id: {fact_id}")
            continue
        if not isinstance(fact_value, str):
            issues.append(f"key_facts[{index}] value must be text")
            continue
        if not isinstance(citations, list) or not all(
            isinstance(citation, str) for citation in citations
        ):
            issues.append(f"key_facts[{index}] citations must be a text array")
            citations = []
        result[fact_id] = (fact_value, tuple(dict.fromkeys(citations)))
    return result


def _candidate_contradictions(
    value: Any,
    issues: list[str],
) -> set[frozenset[str]]:
    if not isinstance(value, list):
        issues.append("contradictions must be an array")
        return set()
    result: set[frozenset[str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            issues.append(f"contradictions[{index}] must be an object")
            continue
        material_ids = item.get("material_ids")
        if (
            not isinstance(material_ids, list)
            or len(material_ids) != 2
            or not all(isinstance(material_id, str) for material_id in material_ids)
            or len(set(material_ids)) != 2
        ):
            issues.append(
                f"contradictions[{index}] must reference two distinct materials"
            )
            continue
        result.add(frozenset(material_ids))
    return result
