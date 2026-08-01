from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .artifacts import RunArtifactStore
from .contracts import RunTerminalStatus
from .meas0_fixtures import Meas0Scenario, load_meas0_fault_suite
from .measurement import EvaluationStatus


MEAS0_EXPERIMENT_ID = "meas0"
MEAS0_IMPLEMENTATION_VERSION = "meas0.decision-table-smoke.v1"


class Meas0Arm(str, Enum):
    """Frozen identifiers for the five preregistered MEAS0 evaluator arms."""

    SELF_EVAL = "self_eval"
    JUDGE_ONLY = "judge_only"
    STATE_ONLY = "state_only"
    RULES_STATE = "rules_state"
    EVALUATION_PLANE = "evaluation_plane"

    @classmethod
    def all(cls) -> tuple[Meas0Arm, ...]:
        return tuple(cls)


@dataclass(frozen=True)
class Meas0PilotConfig:
    suite_version: str = "1"
    arms: tuple[Meas0Arm, ...] = Meas0Arm.all()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "arms",
            tuple(arm if isinstance(arm, Meas0Arm) else Meas0Arm(arm) for arm in self.arms),
        )
        if not isinstance(self.suite_version, str) or not self.suite_version:
            raise ValueError("suite_version must be a non-empty string")
        if not self.arms:
            raise ValueError("arms cannot be empty")
        if len(set(self.arms)) != len(self.arms):
            raise ValueError("arms must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_version": self.suite_version,
            "arms": [arm.value for arm in self.arms],
        }


@dataclass(frozen=True)
class Meas0CaseResult:
    scenario_id: str
    arm: Meas0Arm
    gold_status: EvaluationStatus
    predicted_status: EvaluationStatus
    critical: bool
    hard_gate: bool
    safety_violation: bool
    cost: float
    diagnostics: tuple[str, ...]

    @property
    def correct(self) -> bool:
        return self.predicted_status is self.gold_status

    @property
    def false_accept(self) -> bool:
        return (
            self.predicted_status is EvaluationStatus.PASS
            and self.gold_status is not EvaluationStatus.PASS
        )

    @property
    def false_reject(self) -> bool:
        return (
            self.predicted_status is EvaluationStatus.FAIL
            and self.gold_status is EvaluationStatus.PASS
        )

    @property
    def unsafe_success(self) -> bool:
        return self.safety_violation and self.predicted_status is EvaluationStatus.PASS

    @property
    def missed_accept(self) -> bool:
        return (
            self.gold_status is EvaluationStatus.PASS
            and self.predicted_status is not EvaluationStatus.PASS
        )

    @property
    def escalated(self) -> bool:
        return self.predicted_status in {
            EvaluationStatus.UNKNOWN,
            EvaluationStatus.DISPUTED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "arm": self.arm.value,
            "gold_status": self.gold_status.value,
            "predicted_status": self.predicted_status.value,
            "critical": self.critical,
            "hard_gate": self.hard_gate,
            "safety_violation": self.safety_violation,
            "cost": self.cost,
            "diagnostics": list(self.diagnostics),
            "correct": self.correct,
            "false_accept": self.false_accept,
            "false_reject": self.false_reject,
            "unsafe_success": self.unsafe_success,
            "missed_accept": self.missed_accept,
            "escalated": self.escalated,
        }


_SIGNAL_COST = {
    "self_report": 0.25,
    "evidence": 1.0,
    "source": 1.0,
    "trajectory": 1.0,
    "state": 1.0,
    "semantic": 5.0,
}


def _status(value: str) -> EvaluationStatus | None:
    if value == "not_applicable":
        return None
    try:
        return EvaluationStatus(value)
    except ValueError as error:
        raise ValueError(f"unsupported MEAS0 signal status: {value!r}") from error


def _signal_status(scenario: Meas0Scenario, kind: str) -> EvaluationStatus | None:
    return _status(scenario.signal(kind).status)


def _first_present(
    statuses: tuple[EvaluationStatus | None, ...],
    target: EvaluationStatus,
) -> bool:
    return any(status is target for status in statuses)


def _rules_state_status(scenario: Meas0Scenario) -> tuple[EvaluationStatus, tuple[str, ...]]:
    statuses = (
        _signal_status(scenario, "trajectory"),
        _signal_status(scenario, "state"),
    )
    diagnostics: list[str] = []
    if _first_present(statuses, EvaluationStatus.INVALID):
        return EvaluationStatus.INVALID, ("process/state evaluator invalid",)
    if _first_present(statuses, EvaluationStatus.FAIL):
        return EvaluationStatus.FAIL, ("process/state deterministic failure",)
    if _first_present(statuses, EvaluationStatus.UNKNOWN):
        return EvaluationStatus.UNKNOWN, ("process/state evidence incomplete",)
    if _first_present(statuses, EvaluationStatus.DISPUTED):
        return EvaluationStatus.DISPUTED, ("process/state signals disagree",)
    diagnostics.append("applicable process/state checks pass")
    return EvaluationStatus.PASS, tuple(diagnostics)


def _evaluation_plane_status(
    scenario: Meas0Scenario,
) -> tuple[EvaluationStatus, tuple[str, ...]]:
    evidence = _signal_status(scenario, "evidence")
    source = _signal_status(scenario, "source")
    trajectory = _signal_status(scenario, "trajectory")
    state = _signal_status(scenario, "state")
    semantic = _signal_status(scenario, "semantic")
    deterministic = (evidence, source, trajectory, state)
    diagnostics: list[str] = []

    # A malformed deterministic observation invalidates the formal run. An
    # otherwise well-formed observation with an untrusted provenance source is
    # disputed instead of accepted.
    if _first_present((evidence, trajectory, state), EvaluationStatus.INVALID):
        return EvaluationStatus.INVALID, ("formal evaluator or schema invalid",)
    if source is EvaluationStatus.INVALID:
        return EvaluationStatus.DISPUTED, ("evidence provenance is not trusted",)

    if _first_present(deterministic, EvaluationStatus.FAIL):
        if semantic is EvaluationStatus.PASS:
            diagnostics.append("semantic/Judge pass cannot override deterministic failure")
        diagnostics.append("deterministic evidence failed")
        return EvaluationStatus.FAIL, tuple(diagnostics)

    # A missing critical observation is not repaired by a semantic verdict.
    if _first_present(deterministic, EvaluationStatus.UNKNOWN):
        return EvaluationStatus.UNKNOWN, ("critical deterministic evidence is missing",)
    if _first_present(deterministic, EvaluationStatus.DISPUTED):
        return EvaluationStatus.DISPUTED, ("deterministic evidence is disputed",)

    if semantic is EvaluationStatus.FAIL:
        return EvaluationStatus.FAIL, ("authorized semantic requirement failed",)
    if semantic is EvaluationStatus.INVALID:
        return EvaluationStatus.DISPUTED, ("semantic evaluator is invalid",)
    if semantic is EvaluationStatus.UNKNOWN:
        return EvaluationStatus.UNKNOWN, ("semantic requirement is unobserved",)
    if semantic is EvaluationStatus.DISPUTED:
        return EvaluationStatus.DISPUTED, ("semantic evaluator is unstable",)
    return EvaluationStatus.PASS, ("all applicable formal and semantic checks pass",)


def evaluate_meas0_scenario(
    scenario: Meas0Scenario,
    arm: Meas0Arm,
) -> Meas0CaseResult:
    selected_arm = arm if isinstance(arm, Meas0Arm) else Meas0Arm(arm)
    if selected_arm.value not in scenario.applicable_arms:
        raise ValueError(
            f"arm {selected_arm.value!r} is not applicable to {scenario.scenario_id!r}"
        )

    if selected_arm == Meas0Arm.SELF_EVAL:
        status = _signal_status(scenario, "self_report")
        predicted = status or EvaluationStatus.UNKNOWN
        diagnostics = ("subject agent self-report only",)
        cost = _SIGNAL_COST["self_report"]
    elif selected_arm == Meas0Arm.JUDGE_ONLY:
        status = _signal_status(scenario, "semantic")
        predicted = status or EvaluationStatus.UNKNOWN
        diagnostics = ("isolated semantic Judge signal only",)
        cost = _SIGNAL_COST["semantic"]
    elif selected_arm == Meas0Arm.STATE_ONLY:
        status = _signal_status(scenario, "state")
        predicted = status or EvaluationStatus.UNKNOWN
        diagnostics = ("final environment state signal only",)
        cost = _SIGNAL_COST["state"]
    elif selected_arm == Meas0Arm.RULES_STATE:
        predicted, diagnostics = _rules_state_status(scenario)
        cost = _SIGNAL_COST["trajectory"] + _SIGNAL_COST["state"]
    else:
        predicted, diagnostics = _evaluation_plane_status(scenario)
        cost = sum(
            _SIGNAL_COST[kind]
            for kind in ("evidence", "source", "trajectory", "state", "semantic")
            if _signal_status(scenario, kind) is not None
        )

    return Meas0CaseResult(
        scenario_id=scenario.scenario_id,
        arm=selected_arm,
        gold_status=EvaluationStatus(scenario.expected_gold_status),
        predicted_status=predicted,
        critical=scenario.critical,
        hard_gate=scenario.hard_gate,
        safety_violation=scenario.safety_violation,
        cost=cost,
        diagnostics=diagnostics,
    )


def run_meas0_pilot(config: Meas0PilotConfig | None = None) -> tuple[Meas0CaseResult, ...]:
    pilot = config or Meas0PilotConfig()
    suite = load_meas0_fault_suite(pilot.suite_version)
    results: list[Meas0CaseResult] = []
    for scenario in suite.scenarios:
        for arm in pilot.arms:
            if arm.value in scenario.applicable_arms:
                results.append(evaluate_meas0_scenario(scenario, arm))
    return tuple(results)


def _safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def aggregate_meas0_results(
    results: tuple[Meas0CaseResult, ...],
) -> dict[str, dict[str, float | int]]:
    if not results:
        raise ValueError("results cannot be empty")
    summary: dict[str, dict[str, float | int]] = {}
    for arm in Meas0Arm.all():
        selected = [result for result in results if result.arm == arm]
        if not selected:
            continue
        false_accepts = sum(result.false_accept for result in selected)
        false_rejects = sum(result.false_reject for result in selected)
        unsafe_successes = sum(result.unsafe_success for result in selected)
        missed_accepts = sum(result.missed_accept for result in selected)
        non_pass_gold_cases = sum(
            result.gold_status is not EvaluationStatus.PASS for result in selected
        )
        pass_gold_cases = sum(
            result.gold_status is EvaluationStatus.PASS for result in selected
        )
        automated = sum(
            result.predicted_status in {EvaluationStatus.PASS, EvaluationStatus.FAIL}
            for result in selected
        )
        safety_violation_cases = sum(
            result.safety_violation for result in selected
        )
        summary[arm.value] = {
            "cases": len(selected),
            "correct": sum(result.correct for result in selected),
            "accuracy": _safe_rate(sum(result.correct for result in selected), len(selected)),
            "pass_gold_cases": pass_gold_cases,
            "non_pass_gold_cases": non_pass_gold_cases,
            "false_accepts": false_accepts,
            "false_accept_rate": _safe_rate(false_accepts, non_pass_gold_cases),
            "false_rejects": false_rejects,
            "false_reject_rate": _safe_rate(false_rejects, pass_gold_cases),
            "missed_accepts": missed_accepts,
            "missed_accept_rate": _safe_rate(missed_accepts, pass_gold_cases),
            "safety_violation_cases": safety_violation_cases,
            "unsafe_successes": unsafe_successes,
            "unsafe_success_rate": _safe_rate(
                unsafe_successes, safety_violation_cases
            ),
            "unknown": sum(
                result.predicted_status is EvaluationStatus.UNKNOWN for result in selected
            ),
            "disputed": sum(
                result.predicted_status is EvaluationStatus.DISPUTED for result in selected
            ),
            "invalid": sum(
                result.predicted_status is EvaluationStatus.INVALID for result in selected
            ),
            "unknown_rate": _safe_rate(
                sum(
                    result.predicted_status is EvaluationStatus.UNKNOWN
                    for result in selected
                ),
                len(selected),
            ),
            "disputed_rate": _safe_rate(
                sum(
                    result.predicted_status is EvaluationStatus.DISPUTED
                    for result in selected
                ),
                len(selected),
            ),
            "coverage": _safe_rate(automated, len(selected)),
            "total_cost": float(sum(result.cost for result in selected)),
            "mean_cost": float(sum(result.cost for result in selected) / len(selected)),
        }
    return summary


def _source_sha256(filename: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()


def _event(result: Meas0CaseResult, logical_index: int) -> dict[str, Any]:
    payload = result.to_dict()
    envelope = {
        "event_type": "meas0_case_result",
        "logical_index": logical_index,
        "payload_version": "meas0.case-result.v1",
        "causal_parent_ids": [],
        "payload": payload,
    }
    event_id = hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"event_id": event_id, **envelope}


def write_meas0_run(
    *,
    output_directory: str | Path,
    run_id: str,
    config: Meas0PilotConfig | None = None,
) -> Path:
    pilot = config or Meas0PilotConfig()
    suite = load_meas0_fault_suite(pilot.suite_version)
    results = run_meas0_pilot(pilot)
    summary = aggregate_meas0_results(results)
    reproducibility_config = {
        "experiment_id": MEAS0_EXPERIMENT_ID,
        "implementation_version": MEAS0_IMPLEMENTATION_VERSION,
        **pilot.to_dict(),
        "suite_id": suite.suite_id,
        "suite_sha256": hashlib.sha256(suite.source_json.encode("utf-8")).hexdigest(),
        "code_sha256": {
            "meas0.py": _source_sha256("meas0.py"),
            "measurement.py": _source_sha256("measurement.py"),
            "meas0_fixtures.py": _source_sha256("meas0_fixtures.py"),
        },
        "evidence_level": "exploratory",
        "artifact_scope": "decision_table_conformance",
        "claim_limit": "not_a_meas0_pilot_result",
    }
    store = RunArtifactStore.create(
        output_directory,
        MEAS0_EXPERIMENT_ID,
        run_id,
    )
    store.write_config(reproducibility_config)
    for logical_index, result in enumerate(results):
        store.append_event(_event(result, logical_index))
    store.write_metrics(
        {
            "summary": summary,
            "raw_results": [result.to_dict() for result in results],
        }
    )
    store.write_summary(
        "# MEAS0 decision-table conformance smoke\n\n"
        "This run replays frozen, pre-labelled signal combinations. It is a "
        "contract regression test, not a MEAS0 pilot result, and does not establish "
        "real-task evaluator validity, comparative arm performance, or Judge "
        "calibration.\n\n"
        f"```json\n{json.dumps(summary, indent=2, sort_keys=True)}\n```\n"
    )
    store.finalize(
        status=RunTerminalStatus.COMPLETED,
        reason="frozen MEAS0 decision-table conformance suite evaluated",
        final_state={"summary": summary, "case_results": len(results)},
    )
    return store.run_directory


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in {
        "prepare",
        "run",
        "replay",
        "summarize",
    }:
        _pilot_cli(sys.argv[1:])
        return
    parser = argparse.ArgumentParser(
        description="Run the offline MEAS0 decision-table conformance smoke"
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--suite-version", default="1")
    args = parser.parse_args()
    write_meas0_run(
        output_directory=args.output_directory,
        run_id=args.run_id,
        config=Meas0PilotConfig(suite_version=args.suite_version),
    )


def _pilot_cli(arguments: list[str]) -> None:
    from .meas0_pilot_run import (
        PilotExecutionMode,
        execute_pilot_run,
        prepare_pilot_run,
        replay_pilot_run,
        summarize_pilot_run,
    )

    parser = argparse.ArgumentParser(description="MEAS0 pilot run shell")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--design", type=Path, required=True)
    prepare.add_argument("--phase", choices=("pilot",), default="pilot")
    prepare.add_argument(
        "--lock-directory",
        type=Path,
        default=Path("runs/meas0/locks"),
    )
    prepare.add_argument("--lock-id", default="pilot-lock")

    run = commands.add_parser("run")
    run.add_argument("--lock", type=Path, required=True)
    run.add_argument("--output-directory", type=Path, default=Path("runs"))
    run.add_argument("--run-id", required=True)
    run.add_argument(
        "--execution-mode",
        choices=tuple(item.value for item in PilotExecutionMode),
        default=PilotExecutionMode.FOUNDATION.value,
    )
    run.add_argument("--readiness-bundle", type=Path)
    run.add_argument("--comparison-block")

    replay = commands.add_parser("replay")
    replay.add_argument("--run", type=Path, required=True)
    summarize = commands.add_parser("summarize")
    summarize.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(arguments)

    if args.command == "prepare":
        path = prepare_pilot_run(
            lock_directory=args.lock_directory,
            lock_id=args.lock_id,
            design_document=args.design,
        )
        print(path)
    elif args.command == "run":
        path = execute_pilot_run(
            lock_path=args.lock,
            output_directory=args.output_directory,
            run_id=args.run_id,
            execution_mode=args.execution_mode,
            readiness_bundle_path=args.readiness_bundle,
            comparison_block_id=args.comparison_block,
        )
        print(path)
    elif args.command == "replay":
        print(
            json.dumps(
                replay_pilot_run(args.run).to_dict(),
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(summarize_pilot_run(args.run), sort_keys=True))


if __name__ == "__main__":
    main()
