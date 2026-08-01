"""Exact-byte carrier for the existing MEAS0 Pilot preregistration lock."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


class SourceLockBytesError(ValueError):
    """The supplied source-lock bytes do not match the frozen artifact format."""


_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "arm_case_count",
        "arm_order_manifest",
        "arms",
        "budget_policy",
        "budget_policy_hash",
        "case_count",
        "case_manifest",
        "case_manifest_hash",
        "claim_limit",
        "design_binding",
        "design_document_sha256",
        "environment",
        "evaluator_hashes",
        "experiment_id",
        "fixture_hashes",
        "foundation_runner_version",
        "human_review_available",
        "implementation_version",
        "judge_available",
        "lock_id",
        "mutation_manifest_sha256",
        "mutation_seed",
        "native_measurement_plan_hashes",
        "native_measurement_plans",
        "phase",
        "replay_count",
        "schema_version",
        "source_hashes",
        "task_bundle_hashes",
    }
)
SOURCE_LOCK_V2_SOURCE_NAMES = (
    "__init__.py",
    "artifacts.py",
    "contracts.py",
    "evidence_task.py",
    "meas0.py",
    "meas0_budget.py",
    "meas0_channel_order.py",
    "meas0_detection_oracle.py",
    "meas0_fixtures.py",
    "meas0_formal.py",
    "meas0_formal_derivation.py",
    "meas0_formal_lifecycle.py",
    "meas0_formal_metrics.py",
    "meas0_formal_outcomes.py",
    "meas0_formal_run_store.py",
    "meas0_formal_runner.py",
    "meas0_human.py",
    "meas0_judge_probes.py",
    "meas0_pilot_run.py",
    "meas0_pilot_runner.py",
    "meas0_preflight.py",
    "meas0_protected_artifacts.py",
    "meas0_providers.py",
    "meas0_r1.py",
    "meas0_readiness.py",
    "meas0_stage_cost.py",
    "meas0_trust.py",
    "measurement.py",
    "resources.py",
)
_CLAIM_LIMIT = "pilot_foundation_only_not_a_formal_meas0_pilot_result"
_SOURCE_LOCK_TOKEN = object()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceLockBytesError("source lock JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise SourceLockBytesError(f"source lock JSON contains non-finite value: {value}")


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SourceLockBytesError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class SealedSourceEntry:
    """One exact member of the frozen v2 source-hash map."""

    name: str
    sha256: str

    def __post_init__(self) -> None:
        if self.name not in SOURCE_LOCK_V2_SOURCE_NAMES:
            raise SourceLockBytesError("source entry name is not frozen")
        _require_sha256(self.sha256, "source entry sha256")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "sha256": self.sha256}


@dataclass(frozen=True)
class SealedSourceLockBytes:
    """Caller-supplied canonical lock bytes; never reads a working tree."""

    raw_bytes: bytes
    source_lock_hash: str
    source_entries: tuple[SealedSourceEntry, ...]
    claim_scope: str
    source_restoration_authorized: bool
    production_authorized: bool
    test_only: bool
    _derivation_token: object = field(default=None, repr=False, compare=False)

    @classmethod
    def from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        expected_sha256: str,
    ) -> SealedSourceLockBytes:
        if type(raw_bytes) is not bytes:
            raise SourceLockBytesError("source lock must be supplied as exact bytes")
        _require_sha256(expected_sha256, "expected source lock hash")
        actual = hashlib.sha256(raw_bytes).hexdigest()
        if actual != expected_sha256:
            raise SourceLockBytesError("source lock hash does not match expected hash")
        try:
            value = json.loads(
                raw_bytes.decode("utf-8"),
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_nonfinite,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
        ) as error:
            raise SourceLockBytesError("source lock is not strict JSON") from error
        if not isinstance(value, dict):
            raise SourceLockBytesError("source lock JSON must be an object")
        if frozenset(value) != _TOP_LEVEL_FIELDS:
            raise SourceLockBytesError(
                "source lock fields differ from the existing v2 artifact format"
            )
        if raw_bytes != _canonical_bytes(value):
            raise SourceLockBytesError("source lock bytes are not canonical")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 2
            or value["experiment_id"] != "meas0"
            or value["phase"] != "pilot"
            or value["claim_limit"] != _CLAIM_LIMIT
            or type(value["case_count"]) is not int
            or value["case_count"] != 36
            or type(value["arm_case_count"]) is not int
            or value["arm_case_count"] != 180
        ):
            raise SourceLockBytesError(
                "source lock does not match the existing Pilot v2 contract"
            )
        source_hashes = value["source_hashes"]
        if not isinstance(source_hashes, dict) or tuple(source_hashes) != (
            SOURCE_LOCK_V2_SOURCE_NAMES
        ):
            raise SourceLockBytesError(
                "source entries differ from exact ordered v2 membership"
            )
        entries = tuple(
            SealedSourceEntry(
                name=name,
                sha256=_require_sha256(digest, f"source hash for {name}"),
            )
            for name, digest in source_hashes.items()
        )
        return cls(
            raw_bytes=raw_bytes,
            source_lock_hash=actual,
            source_entries=entries,
            claim_scope="simulated_nonclaim",
            source_restoration_authorized=False,
            production_authorized=False,
            test_only=True,
            _derivation_token=_SOURCE_LOCK_TOKEN,
        )

    def __post_init__(self) -> None:
        if self._derivation_token is not _SOURCE_LOCK_TOKEN:
            raise SourceLockBytesError(
                "sealed source lock must be created from canonical bytes"
            )
        if (
            hashlib.sha256(self.raw_bytes).hexdigest() != self.source_lock_hash
            or tuple(item.name for item in self.source_entries)
            != SOURCE_LOCK_V2_SOURCE_NAMES
        ):
            raise SourceLockBytesError("sealed source lock derivation is invalid")
        if (
            self.claim_scope != "simulated_nonclaim"
            or self.source_restoration_authorized is not False
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise SourceLockBytesError(
                "sealed source lock cannot carry restoration or production authority"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": "meas0.sealed-source-lock-bytes.v3",
            "version": 1,
            "raw_bytes_base64": base64.b64encode(self.raw_bytes).decode("ascii"),
            "source_lock_hash": self.source_lock_hash,
            "source_entries": [item.to_dict() for item in self.source_entries],
            "claim_scope": self.claim_scope,
            "source_restoration_authorized": self.source_restoration_authorized,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def carrier_hash(self) -> str:
        return _canonical_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "carrier_hash": self.carrier_hash}


__all__ = [
    "SOURCE_LOCK_V2_SOURCE_NAMES",
    "SealedSourceEntry",
    "SealedSourceLockBytes",
    "SourceLockBytesError",
]
