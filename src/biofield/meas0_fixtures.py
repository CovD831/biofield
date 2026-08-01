from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator

from .resources import fixture_root


MEAS0_ARMS = (
    "self_eval",
    "judge_only",
    "state_only",
    "rules_state",
    "evaluation_plane",
)
MEAS0_PROTOCOL_SCENARIOS = tuple(range(1, 15))
MEAS0_SIGNAL_KINDS = (
    "self_report",
    "evidence",
    "source",
    "trajectory",
    "state",
    "semantic",
)

_SUITE_FILES = {"1": "synthetic_faults.v1.json"}
_SCHEMA_FILES = {"1": "schema.v1.json"}
_REVIEW_STATUSES = frozenset({"unknown", "disputed"})


class Meas0FixtureError(ValueError):
    """Raised when a packaged MEAS0 fixture violates its frozen contract."""


@dataclass(frozen=True)
class Meas0Signal:
    kind: str
    status: str
    observed_value: str
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in MEAS0_SIGNAL_KINDS:
            raise ValueError(f"unsupported MEAS0 signal kind: {self.kind!r}")
        if not isinstance(self.provenance_refs, tuple):
            raise TypeError("provenance_refs must be an immutable tuple")


@dataclass(frozen=True)
class Meas0Scenario:
    scenario_id: str
    title: str
    protocol_scenario: int | None
    fault_category: str
    expected_gold_status: str
    critical: bool
    hard_gate: bool
    safety_violation: bool
    applicable_arms: tuple[str, ...]
    human_review_required: bool
    signals: tuple[Meas0Signal, ...]

    def signal(self, kind: str) -> Meas0Signal:
        for signal in self.signals:
            if signal.kind == kind:
                return signal
        raise Meas0FixtureError(
            f"scenario {self.scenario_id!r} has no {kind!r} signal"
        )


@dataclass(frozen=True)
class Meas0FixtureSuite:
    schema_id: str
    schema_version: str
    suite_id: str
    suite_version: str
    protocol_ref: str
    arms: tuple[str, ...]
    scenarios: tuple[Meas0Scenario, ...]
    source_json: str

    def scenario(self, scenario_id: str) -> Meas0Scenario:
        for scenario in self.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise Meas0FixtureError(f"unknown MEAS0 scenario: {scenario_id!r}")


def load_meas0_fault_suite(version: str = "1") -> Meas0FixtureSuite:
    """Load a frozen synthetic MEAS0 fault suite from package data.

    Version lookup is allow-listed before any path is constructed. This keeps
    callers from turning a version string into an arbitrary package path.
    """

    normalized_version = _supported_version(version, _SUITE_FILES)
    path = _meas0_fixture_root() / _SUITE_FILES[normalized_version]
    payload = _load_json_object(path, label="MEAS0 fixture")
    return parse_meas0_fault_suite(
        payload,
        expected_suite_version=normalized_version,
    )


def parse_meas0_fault_suite(
    payload: Mapping[str, object],
    *,
    expected_suite_version: str = "1",
) -> Meas0FixtureSuite:
    """Validate and materialize an in-memory fixture payload.

    This entry point exists for mutation tests and fixture review tooling. The
    schema itself is always loaded from trusted package data, not from the
    payload being validated.
    """

    expected_version = _supported_version(expected_suite_version, _SUITE_FILES)
    if not isinstance(payload, Mapping):
        raise Meas0FixtureError("MEAS0 fixture must be a JSON object")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or schema_version not in _SCHEMA_FILES:
        raise Meas0FixtureError(
            f"unsupported schema version: {schema_version!r}"
        )

    schema_path = _meas0_fixture_root() / _SCHEMA_FILES[schema_version]
    schema = _load_json_object(schema_path, label="MEAS0 fixture schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise Meas0FixtureError(
            f"fixture schema validation failed at {location}: {first.message}"
        )

    suite_version = payload["suite_version"]
    if suite_version != expected_version:
        raise Meas0FixtureError(
            "fixture suite_version does not match requested version: "
            f"{suite_version!r} != {expected_version!r}"
        )

    raw_scenarios = payload["scenarios"]
    assert isinstance(raw_scenarios, list)
    scenario_ids = [scenario["scenario_id"] for scenario in raw_scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise Meas0FixtureError("duplicate scenario_id in MEAS0 fixture")

    covered_protocol_scenarios = {
        scenario["protocol_scenario"]
        for scenario in raw_scenarios
        if scenario["protocol_scenario"] is not None
    }
    expected_protocol_scenarios = set(MEAS0_PROTOCOL_SCENARIOS)
    if covered_protocol_scenarios != expected_protocol_scenarios:
        raise Meas0FixtureError(
            "protocol scenario coverage mismatch: "
            f"expected {sorted(expected_protocol_scenarios)}, "
            f"got {sorted(covered_protocol_scenarios)}"
        )

    protocol_numbers = [
        scenario["protocol_scenario"]
        for scenario in raw_scenarios
        if scenario["protocol_scenario"] is not None
    ]
    if len(protocol_numbers) != len(set(protocol_numbers)):
        raise Meas0FixtureError("duplicate protocol scenario in MEAS0 fixture")

    scenarios = tuple(_parse_scenario(scenario) for scenario in raw_scenarios)
    for scenario in scenarios:
        if scenario.applicable_arms != MEAS0_ARMS:
            raise Meas0FixtureError(
                f"scenario {scenario.scenario_id!r} must preserve the common five-arm cohort"
            )
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    successful_baseline = scenario_by_id.get("meas0.control.success")
    if (
        successful_baseline is None
        or successful_baseline.protocol_scenario is not None
        or successful_baseline.fault_category != "none"
        or successful_baseline.expected_gold_status != "pass"
    ):
        raise Meas0FixtureError("MEAS0 fixture has no successful baseline")
    clean_failure = scenario_by_id.get("meas0.control.clean_failure")
    if (
        clean_failure is None
        or clean_failure.protocol_scenario is not None
        or clean_failure.fault_category != "clean_failure"
        or clean_failure.expected_gold_status != "fail"
    ):
        raise Meas0FixtureError("MEAS0 fixture has no simple clean failure")

    source_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return Meas0FixtureSuite(
        schema_id=str(payload["schema_id"]),
        schema_version=schema_version,
        suite_id=str(payload["suite_id"]),
        suite_version=str(suite_version),
        protocol_ref=str(payload["protocol_ref"]),
        arms=tuple(str(arm) for arm in payload["arms"]),
        scenarios=scenarios,
        source_json=source_json,
    )


def _parse_scenario(raw: Mapping[str, object]) -> Meas0Scenario:
    expected_status = str(raw["expected_gold_status"])
    human_review_required = bool(raw["human_review_required"])
    if expected_status in _REVIEW_STATUSES and not human_review_required:
        raise Meas0FixtureError(
            f"scenario {raw['scenario_id']!r} requires human review "
            f"for {expected_status!r} gold status"
        )
    if bool(raw["hard_gate"]) and not bool(raw["critical"]):
        raise Meas0FixtureError(
            f"scenario {raw['scenario_id']!r} hard_gate must be critical"
        )

    raw_signals = raw["signals"]
    assert isinstance(raw_signals, Mapping)
    signals = tuple(
        Meas0Signal(
            kind=kind,
            status=str(raw_signals[kind]["status"]),
            observed_value=str(raw_signals[kind]["observed_value"]),
            provenance_refs=tuple(
                str(ref) for ref in raw_signals[kind]["provenance_refs"]
            ),
        )
        for kind in MEAS0_SIGNAL_KINDS
    )
    protocol_scenario = raw["protocol_scenario"]
    return Meas0Scenario(
        scenario_id=str(raw["scenario_id"]),
        title=str(raw["title"]),
        protocol_scenario=(
            int(protocol_scenario) if protocol_scenario is not None else None
        ),
        fault_category=str(raw["fault_category"]),
        expected_gold_status=expected_status,
        critical=bool(raw["critical"]),
        hard_gate=bool(raw["hard_gate"]),
        safety_violation=bool(raw["safety_violation"]),
        applicable_arms=tuple(str(arm) for arm in raw["applicable_arms"]),
        human_review_required=human_review_required,
        signals=signals,
    )


def _supported_version(version: object, supported: Mapping[str, str]) -> str:
    if not isinstance(version, str) or version not in supported:
        raise Meas0FixtureError(
            f"unsupported MEAS0 fixture version: {version!r}"
        )
    return version


def _meas0_fixture_root() -> Path:
    return fixture_root() / "meas0"


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Meas0FixtureError(f"cannot load {label} {path.name!r}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Meas0FixtureError(f"{label} {path.name!r} must contain a JSON object")
    return payload
