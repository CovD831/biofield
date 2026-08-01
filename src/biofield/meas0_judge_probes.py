"""Registered, independent instability probes for MEAS0 Judge qualification.

This module is an offline contract.  It deliberately contains no protected
corpus content, provider transport, production signature, or live-call budget.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .measurement import EvaluationStatus
from .meas0_readiness import RateEstimate


class JudgeProbeContractError(ValueError):
    """Raised when probe relations could manufacture or mix evidence."""


class ProbeKind(str, Enum):
    ORDER = "order"
    STYLE = "style"
    REPEAT = "repeat"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgeProbeContractError(f"{label} must be non-empty text")
    return value


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise JudgeProbeContractError(f"{label} must be a lowercase SHA-256")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


@dataclass(frozen=True)
class JudgeProbeCall:
    call_id: str
    item_id: str
    presentation: str
    presentation_hash: str
    schedule_id: str

    def __post_init__(self) -> None:
        _text(self.call_id, "probe call_id")
        _text(self.item_id, "probe item_id")
        _text(self.presentation, "probe presentation")
        _hash(self.presentation_hash, "probe presentation_hash")
        _text(self.schedule_id, "probe schedule_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "call_id": self.call_id,
            "item_id": self.item_id,
            "presentation": self.presentation,
            "presentation_hash": self.presentation_hash,
            "schedule_id": self.schedule_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> JudgeProbeCall:
        if not isinstance(value, Mapping) or set(value) != {
            "call_id",
            "item_id",
            "presentation",
            "presentation_hash",
            "schedule_id",
        }:
            raise JudgeProbeContractError("serialized probe call is invalid")
        return cls(
            call_id=value["call_id"],
            item_id=value["item_id"],
            presentation=value["presentation"],
            presentation_hash=value["presentation_hash"],
            schedule_id=value["schedule_id"],
        )


@dataclass(frozen=True)
class JudgeProbeRelation:
    relation_id: str
    item_id: str
    kind: ProbeKind
    left_call_id: str
    right_call_id: str

    def __post_init__(self) -> None:
        _text(self.relation_id, "probe relation_id")
        _text(self.item_id, "probe relation item_id")
        if not isinstance(self.kind, ProbeKind):
            try:
                object.__setattr__(self, "kind", ProbeKind(self.kind))
            except (TypeError, ValueError) as error:
                raise JudgeProbeContractError("probe kind is invalid") from error
        _text(self.left_call_id, "left probe call_id")
        _text(self.right_call_id, "right probe call_id")
        if self.left_call_id == self.right_call_id:
            raise JudgeProbeContractError("probe relation requires two calls")

    def to_dict(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "item_id": self.item_id,
            "kind": self.kind.value,
            "left_call_id": self.left_call_id,
            "right_call_id": self.right_call_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> JudgeProbeRelation:
        if not isinstance(value, Mapping) or set(value) != {
            "relation_id",
            "item_id",
            "kind",
            "left_call_id",
            "right_call_id",
        }:
            raise JudgeProbeContractError("serialized probe relation is invalid")
        return cls(
            relation_id=value["relation_id"],
            item_id=value["item_id"],
            kind=ProbeKind(value["kind"]),
            left_call_id=value["left_call_id"],
            right_call_id=value["right_call_id"],
        )


@dataclass(frozen=True)
class JudgeProbeManifest:
    manifest_id: str
    version: int
    judge_set_hash: str
    protected_corpus_hash: str
    calls: tuple[JudgeProbeCall, ...]
    relations: tuple[JudgeProbeRelation, ...]
    test_only: bool

    def __post_init__(self) -> None:
        _text(self.manifest_id, "probe manifest_id")
        if self.version != 2:
            raise JudgeProbeContractError("probe manifest version must be two")
        _hash(self.judge_set_hash, "Judge set hash")
        _hash(self.protected_corpus_hash, "protected corpus hash")
        object.__setattr__(self, "calls", tuple(self.calls))
        object.__setattr__(self, "relations", tuple(self.relations))
        if not isinstance(self.test_only, bool):
            raise JudgeProbeContractError("test_only must be boolean")
        if (
            len(self.calls) != 48 * 6
            or not all(isinstance(call, JudgeProbeCall) for call in self.calls)
            or len({call.call_id for call in self.calls}) != len(self.calls)
            or len({call.schedule_id for call in self.calls}) != len(self.calls)
        ):
            raise JudgeProbeContractError(
                "probe manifest requires 288 unique registered calls"
            )
        call_by_id = {call.call_id: call for call in self.calls}
        if (
            len(self.relations) != 48 * 3
            or not all(
                isinstance(relation, JudgeProbeRelation) for relation in self.relations
            )
            or len({relation.relation_id for relation in self.relations})
            != len(self.relations)
        ):
            raise JudgeProbeContractError(
                "probe manifest requires 144 unique registered relations"
            )
        pairs: set[frozenset[str]] = set()
        item_kinds: Counter[tuple[str, ProbeKind]] = Counter()
        for relation in self.relations:
            try:
                left = call_by_id[relation.left_call_id]
                right = call_by_id[relation.right_call_id]
            except KeyError as error:
                raise JudgeProbeContractError(
                    "probe relation references an unknown call"
                ) from error
            if left.item_id != relation.item_id or right.item_id != relation.item_id:
                raise JudgeProbeContractError("probe relation crosses items")
            pair = frozenset((left.call_id, right.call_id))
            if pair in pairs:
                raise JudgeProbeContractError("a probe call pair cannot be reused")
            pairs.add(pair)
            item_kinds[(relation.item_id, relation.kind)] += 1
            if relation.kind is ProbeKind.REPEAT:
                if left.presentation_hash != right.presentation_hash:
                    raise JudgeProbeContractError(
                        "repeat probes require identical presentation bytes"
                    )
            elif left.presentation_hash == right.presentation_hash:
                raise JudgeProbeContractError(
                    "order/style probes require distinct registered presentations"
                )
        expected_items = tuple(f"item-{index:02d}" for index in range(48))
        if self.item_ids != expected_items or any(
            item_kinds[(item_id, kind)] != 1
            for item_id in expected_items
            for kind in ProbeKind
        ):
            raise JudgeProbeContractError(
                "each frozen item requires one order, style, and repeat relation"
            )

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(sorted({call.item_id for call in self.calls}))

    @property
    def production_ready(self) -> bool:
        # A protected manifest contract is not a signed formal lock.
        return False

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "judge_set_hash": self.judge_set_hash,
            "protected_corpus_hash": self.protected_corpus_hash,
            "calls": [call.to_dict() for call in self.calls],
            "relations": [relation.to_dict() for relation in self.relations],
            "test_only": self.test_only,
        }

    @classmethod
    def from_dict(cls, value: object) -> JudgeProbeManifest:
        if not isinstance(value, Mapping) or set(value) != {
            "manifest_id",
            "version",
            "judge_set_hash",
            "protected_corpus_hash",
            "calls",
            "relations",
            "test_only",
            "contract_hash",
        }:
            raise JudgeProbeContractError("serialized probe manifest is invalid")
        try:
            result = cls(
                manifest_id=value["manifest_id"],
                version=value["version"],
                judge_set_hash=value["judge_set_hash"],
                protected_corpus_hash=value["protected_corpus_hash"],
                calls=tuple(JudgeProbeCall.from_dict(item) for item in value["calls"]),
                relations=tuple(
                    JudgeProbeRelation.from_dict(item) for item in value["relations"]
                ),
                test_only=value["test_only"],
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, JudgeProbeContractError):
                raise
            raise JudgeProbeContractError(
                "serialized probe manifest is invalid"
            ) from error
        if value["contract_hash"] != result.contract_hash:
            raise JudgeProbeContractError("serialized probe manifest hash mismatch")
        return result


@dataclass(frozen=True)
class JudgeProbeRates:
    order_flip: RateEstimate
    style_flip: RateEstimate
    repeat_disagreement: RateEstimate


def _wilson(successes: int, denominator: int) -> RateEstimate:
    z = 1.959963984540054
    proportion = successes / denominator
    adjustment = z * z / denominator
    center = (proportion + adjustment / 2) / (1 + adjustment)
    spread = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator
            + z * z / (4 * denominator * denominator)
        )
        / (1 + adjustment)
    )
    return RateEstimate(
        value=proportion,
        lower=min(proportion, max(0.0, center - spread)),
        upper=max(proportion, min(1.0, center + spread)),
        denominator=denominator,
    )


def derive_probe_rates(
    manifest: JudgeProbeManifest,
    verdicts: Mapping[str, EvaluationStatus],
) -> JudgeProbeRates:
    if not isinstance(manifest, JudgeProbeManifest):
        raise JudgeProbeContractError("typed probe manifest is required")
    if set(verdicts) != {call.call_id for call in manifest.calls}:
        raise JudgeProbeContractError(
            "probe verdict IDs must exactly match the registered calls"
        )
    normalized: dict[str, EvaluationStatus] = {}
    for call_id, verdict in verdicts.items():
        try:
            normalized[call_id] = (
                verdict
                if isinstance(verdict, EvaluationStatus)
                else EvaluationStatus(verdict)
            )
        except (TypeError, ValueError) as error:
            raise JudgeProbeContractError("probe verdict is invalid") from error
    disagreements = {kind: 0 for kind in ProbeKind}
    for relation in manifest.relations:
        if normalized[relation.left_call_id] is not normalized[relation.right_call_id]:
            disagreements[relation.kind] += 1
    return JudgeProbeRates(
        order_flip=_wilson(disagreements[ProbeKind.ORDER], 48),
        style_flip=_wilson(disagreements[ProbeKind.STYLE], 48),
        repeat_disagreement=_wilson(disagreements[ProbeKind.REPEAT], 48),
    )


__all__ = [
    "JudgeProbeCall",
    "JudgeProbeContractError",
    "JudgeProbeManifest",
    "JudgeProbeRates",
    "JudgeProbeRelation",
    "ProbeKind",
    "derive_probe_rates",
]
