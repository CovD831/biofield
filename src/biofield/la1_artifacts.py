from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .admission import ActionToolPolicy, AdmissionPolicy
from .artifacts import (
    ArtifactError,
    RunArtifactSchemas,
    RunArtifactStore,
    RunFinalizedError,
)
from .contracts import (
    ActionStatus,
    AgentBid,
    AgentIntent,
    LocalFieldObservation,
    OrganizationSnapshot,
    ResourceAmount,
    RunTerminalStatus,
)
from .failure_checkpoint import (
    FailureReorganizationCheckpoint,
    create_failure_reorganization_checkpoint,
    resume_failure_reorganization,
)
from .failure_runtime import (
    ScriptedFailureExecution,
    replay_failure_reorganization,
    run_failure_reorganization,
)
from .gate_episode import (
    PrivateAgentState,
    replay_gate_episode,
    run_gate_episode,
)
from .local_runtime import HarnessRuntimeEvent
from .la1_governance import run_governance_evidence
from .multi_admission import BidCandidate, MultiAdmissionPolicy


EXPERIMENT_ID = "la1-scripted"
CONFIG_SCHEMA_VERSION = "la1.config.v1"
METRICS_SCHEMA_VERSION = "la1.metrics.v2"
RUNNER_VERSION = "la1-artifact-runner-v5"
SCENARIOS = frozenset({"success", "failure_recovery", "governance_paths"})
_COMPLETED_FINALIZATION_REASON = "scripted LA1 scenario completed and replayed"
_FAILED_FINALIZATION_REASON = "LA1 scenario execution failed and was retained"

_METRIC_DEFINITIONS = {
    "contract_validity": (
        "valid persisted public runtime events / all persisted public runtime events"
    ),
    "admission_rejection_by_reason": (
        "rejected public admission decisions grouped by frozen reason / all "
        "public admission decisions"
    ),
    "illegal_rejection": (
        "illegal proposal attempts rejected without side effects / all "
        "illegal proposal attempts; zero denominator is not_applicable"
    ),
    "time_to_first_commitment": (
        "one-based public event count from the first persisted event through "
        "the first materialized Commitment"
    ),
    "duplicate_effort": (
        "OrganizationSnapshot duplicate count / executed Action count"
    ),
    "refusal_recovery": (
        "refusals followed by a different admitted agent / all refusals"
    ),
    "communication": (
        "delivered payload bytes, messages, and resource cost; normalized "
        "resource cost / accepted contribution"
    ),
    "state_update_provenance": (
        "public local-state transitions with complete causal source "
        "references / all public local-state transitions"
    ),
    "public_terminal_hash": ("SHA-256 of the replayed public terminal projection"),
    "ledger_conservation": (
        "sum(shared_pool, escrow, reserved, spent) == frozen run budget for "
        "every resource type"
    ),
    "residual_over_cycles": (
        "ordered public Residual revisions and requirement statuses"
    ),
    "reorganization_count": ("count of post-failure public readmission events"),
    "completion_recovery_cycles": (
        "terminal Commitment transition counts; recovery cycles equal "
        "post-failure readmissions"
    ),
    "organization_snapshot_stats": (
        "counts projected from the terminal OrganizationSnapshot"
    ),
    "cost_vector": (
        "complete protocol §3.2 runtime cost fields; unavailable model/Judge/"
        "human quantities are explicit zeros for scripted agents"
    ),
}
_COST_VECTOR_FIELDS = (
    "model_calls",
    "input_tokens",
    "output_tokens",
    "tool_calls",
    "wall_time_ms",
    "cpu_time_ms",
    "bytes_transferred",
    "communication_messages",
    "communication_tokens",
    "state_update_calls",
    "verifier_calls",
    "deterministic_check_calls",
    "judge_calls",
    "human_escalations",
    "retry_count",
)


class LA1ArtifactError(ValueError):
    """An LA1 evidence-package operation failed."""


class LA1ArtifactIntegrityError(LA1ArtifactError):
    """A persisted LA1 artifact failed sealing or semantic replay."""


class LA1RunExecutionError(LA1ArtifactError):
    """The requested run failed and was retained as a sealed failed run."""

    def __init__(self, message: str, run_directory: Path) -> None:
        self.run_directory = run_directory
        super().__init__(message)


class LA1CLIUsageError(LA1ArtifactError):
    """CLI arguments did not satisfy the machine-readable contract."""


@dataclass(frozen=True, kw_only=True)
class LA1RunExecution:
    run_directory: Path
    scenario: str
    status: str
    events: tuple[HarnessRuntimeEvent, ...]
    organization_snapshot: OrganizationSnapshot | None
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str | None
    metrics: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class _ScenarioExecution:
    events: tuple[HarnessRuntimeEvent, ...]
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str
    checkpoint: FailureReorganizationCheckpoint | None
    extra_artifacts: Mapping[str, Mapping[str, Any]]


_OBJECT_SCHEMA: dict[str, Any] = {"type": "object"}
LA1_ARTIFACT_SCHEMAS = RunArtifactSchemas(
    config={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "experiment_id",
            "run_id",
            "scenario",
            "runner_version",
            "run_budget",
            "scenario_parameters",
            "fixture_sha256",
            "source_sha256",
            "environment",
            "exclusion_policy",
        ],
        "properties": {
            "schema_version": {"const": CONFIG_SCHEMA_VERSION},
            "experiment_id": {"const": EXPERIMENT_ID},
            "run_id": {"type": "string", "minLength": 1},
            "scenario": {"enum": sorted(SCENARIOS)},
            "runner_version": {"const": RUNNER_VERSION},
            "run_budget": _OBJECT_SCHEMA,
            "scenario_parameters": _OBJECT_SCHEMA,
            "fixture_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "source_sha256": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
            },
            "environment": _OBJECT_SCHEMA,
            "exclusion_policy": _OBJECT_SCHEMA,
        },
    },
    event={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "event_id",
            "event_type",
            "event_schema_version",
            "public_state_revision",
            "causal_parent_ids",
            "payload",
            "payload_sha256",
        ],
        "properties": {
            "event_id": {"type": "string", "minLength": 1},
            "event_type": {"type": "string", "minLength": 1},
            "event_schema_version": {"const": 1},
            "public_state_revision": {"type": "integer", "minimum": 0},
            "causal_parent_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "payload": _OBJECT_SCHEMA,
            "payload_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        },
    },
    metrics={
        "type": "object",
        "required": [
            "schema_version",
            "scenario",
            "run_validity",
            "metric_definitions",
            "cost_vector",
        ],
        "properties": {
            "schema_version": {"const": METRICS_SCHEMA_VERSION},
            "scenario": {"enum": sorted(SCENARIOS)},
            "run_validity": {"enum": ["valid", "invalid-run"]},
            "metric_definitions": _OBJECT_SCHEMA,
            "cost_vector": {
                "type": "object",
                "required": list(_COST_VECTOR_FIELDS),
            },
        },
    },
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LA1ArtifactIntegrityError(f"cannot read {path.name} as JSON") from error
    if not isinstance(value, dict):
        raise LA1ArtifactIntegrityError(f"{path.name} must contain an object")
    return value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _git_value(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=_repo_root(),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return completed.stdout.strip() or "clean"


def _source_hashes() -> dict[str, str]:
    package_root = Path(__file__).resolve().parent
    module_names = (
        "__init__.py",
        "admission.py",
        "artifacts.py",
        "commitment.py",
        "communication.py",
        "contracts.py",
        "dispute_runtime.py",
        "gate_episode.py",
        "failure_runtime.py",
        "failure_checkpoint.py",
        "ledger.py",
        "la1_governance.py",
        "local_runtime.py",
        "local_state.py",
        "multi_admission.py",
        "organization.py",
        "refusal_runtime.py",
        "residual.py",
        "la1_artifacts.py",
    )
    return {
        f"src/biofield/{name}": _file_sha256(package_root / name)
        for name in module_names
    }


def _environment() -> dict[str, Any]:
    dependencies: dict[str, str] = {}
    for name in ("jsonschema", "numpy"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "unavailable"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependencies": dependencies,
        "git_commit": _git_value("rev-parse", "HEAD"),
        "dirty_state": tuple(
            line for line in _git_value("status", "--short").splitlines() if line
        ),
        "model": "none-scripted-agents",
        "tools": {
            "artifact_runner": RUNNER_VERSION,
            "scripted_policy": "gate-scripted-policy-v1",
        },
    }


def _success_private_states() -> dict[str, PrivateAgentState]:
    return {
        "agent-a": PrivateAgentState(
            state_version=0,
            collect_capability=0.9,
            verify_capability=0.2,
            caution=0.1,
            consumed_evidence_refs=(),
        ),
        "agent-b": PrivateAgentState(
            state_version=0,
            collect_capability=0.2,
            verify_capability=0.9,
            caution=0.1,
            consumed_evidence_refs=(),
        ),
        "agent-c": PrivateAgentState(
            state_version=0,
            collect_capability=0.3,
            verify_capability=0.3,
            caution=0.95,
            consumed_evidence_refs=(),
        ),
    }


def _success_inputs(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "private_states": _success_private_states(),
        "run_budget": (ResourceAmount("tokens", 100),),
        "initial_at": "2026-07-30T10:00:30+08:00",
        "refused_at": "2026-07-30T10:00:40+08:00",
        "takeover_at": "2026-07-30T10:01:00+08:00",
        "requested_at": "2026-07-30T10:01:10+08:00",
        "delivered_at": "2026-07-30T10:01:20+08:00",
        "received_at": "2026-07-30T10:01:21+08:00",
        "consumed_at": "2026-07-30T10:01:22+08:00",
        "followup_at": "2026-07-30T10:01:30+08:00",
        "finished_at": "2026-07-30T10:01:50+08:00",
    }


def _failure_candidate(agent: str, bid_id: str) -> BidCandidate:
    observation = LocalFieldObservation(
        schema_version=1,
        observation_id=f"obs-{agent}",
        agent_id=agent,
        task_id="task-1",
        requirement_schema_version=1,
        public_state_revision=0,
        visible_requirement_signals=("sources",),
        congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 100),),
        risk_flags=(),
        source_event_ids=("task-start",),
        field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:10:00+08:00",
    )
    intent = AgentIntent(
        schema_version=1,
        intent_id=f"intent-{agent}",
        agent_id=agent,
        observation_id=observation.observation_id,
        local_state_version=0,
        target_requirement_id="sources",
        proposed_action_family="lookup",
        expected_evidence_type="source",
        expected_marginal_progress=0.5,
        confidence=0.5,
        uncertainty=0.5,
        requested_resource_bounds=(ResourceAmount("tokens", 40),),
        dependency_refs=(),
        expires_at="2026-07-30T09:09:00+08:00",
    )
    bid = AgentBid(
        schema_version=1,
        bid_id=bid_id,
        agent_id=agent,
        intent_id=intent.intent_id,
        observation_id=observation.observation_id,
        target_requirement_id="sources",
        capacity_commitment=1,
        estimated_cost_vector=(ResourceAmount("tokens", 30),),
        requested_budget_vector=(ResourceAmount("tokens", 40),),
        expected_completion_window=(
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:08:00+08:00",
        ),
        duplication_tolerance=0,
        communication_needs=(),
    )
    return BidCandidate(
        bid=bid,
        intent=intent,
        observation=observation,
        exploration_eligible=False,
    )


def _failure_inputs(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "candidates": (
            _failure_candidate("a", "bid-a"),
            _failure_candidate("b", "bid-b"),
            _failure_candidate("c", "bid-c"),
        ),
        "admission_policy": AdmissionPolicy(
            schema_version=1,
            policy_version="admission-v1",
            action_tool_policies=(ActionToolPolicy("lookup", ("fixture.read",)),),
        ),
        "multi_policy": MultiAdmissionPolicy(
            schema_version=1,
            policy_version="multi-v1",
            max_concurrent_commitments=1,
            max_commitments_per_requirement=1,
            exploration_min_slots=0,
            tie_break_rule="bid_id_lexicographic",
        ),
        "run_budget": (ResourceAmount("tokens", 100),),
        "initial_at": "2026-07-30T09:00:30+08:00",
        "initial_execution": ScriptedFailureExecution(
            execution_id="execution-a",
            agent_id="a",
            requested_resources=(ResourceAmount("tokens", 30),),
            actual_cost=(ResourceAmount("tokens", 10),),
            status=ActionStatus.FAILED,
            started_at="2026-07-30T09:01:10+08:00",
            finished_at="2026-07-30T09:01:20+08:00",
        ),
        "readmission_at": "2026-07-30T09:02:00+08:00",
        "takeover_execution": ScriptedFailureExecution(
            execution_id="execution-b",
            agent_id="b",
            requested_resources=(ResourceAmount("tokens", 30),),
            actual_cost=(ResourceAmount("tokens", 20),),
            status=ActionStatus.SUCCEEDED,
            started_at="2026-07-30T09:03:10+08:00",
            finished_at="2026-07-30T09:03:20+08:00",
        ),
    }


def _fixture_projection(scenario: str, run_id: str) -> dict[str, Any]:
    if scenario == "success":
        inputs = _success_inputs(run_id)
    elif scenario == "failure_recovery":
        inputs = _failure_inputs(run_id)
    elif scenario == "governance_paths":
        return {
            "run_id": run_id,
            "coverage_contract_version": "la1-governance-coverage-v1",
        }
    else:
        raise LA1ArtifactError(f"unknown LA1 scenario: {scenario}")
    projected: dict[str, Any] = {}
    for key, value in inputs.items():
        if key == "run_id":
            continue
        if isinstance(value, tuple):
            projected[key] = [
                item.to_dict() if hasattr(item, "to_dict") else str(item)
                for item in value
            ]
        elif isinstance(value, Mapping):
            projected[key] = {
                item_key: (
                    item_value.to_dict()
                    if hasattr(item_value, "to_dict")
                    else str(item_value)
                )
                for item_key, item_value in sorted(value.items())
            }
        elif hasattr(value, "to_dict"):
            projected[key] = value.to_dict()
        else:
            projected[key] = str(value)
    return projected


def _scenario_parameters(scenario: str) -> dict[str, Any]:
    if scenario == "success":
        inputs = _success_inputs("fixture-run-id")
        return {
            "agent_count": 3,
            "admission_policy_version": "gate-admission-v1",
            "communication_policy_version": "gate-communication-v1",
            "field_policy_version": "non-prescriptive-field-v1",
            "multi_admission_policy_version": "gate-multi-v1",
            "scripted_policy_version": "private-state-policy-v1",
            "private_state_fixture_sha256": _sha256(
                _fixture_projection("success", "fixture-run-id")["private_states"]
            ),
            "private_state_values": "omitted-hash-only",
            "timestamps": {
                key: value for key, value in inputs.items() if key.endswith("_at")
            },
        }
    if scenario == "failure_recovery":
        inputs = _failure_inputs("fixture-run-id")
        return {
            "agent_count": len(inputs["candidates"]),
            "admission_policy_version": (inputs["admission_policy"].policy_version),
            "checkpoint_boundary": "failure_settlement",
            "multi_admission_policy_version": (inputs["multi_policy"].policy_version),
            "private_state_values": "not-used",
            "timestamps": {
                "initial_at": inputs["initial_at"],
                "readmission_at": inputs["readmission_at"],
            },
        }
    if scenario == "governance_paths":
        return {
            "agent_count": 3,
            "admission_policy_version": "governance-paths-v1",
            "multi_admission_policy_version": "governance-paths-v1",
            "private_state_values": "not-used",
            "coverage_contract_version": "la1-governance-coverage-v1",
        }
    raise LA1ArtifactError(f"unknown LA1 scenario: {scenario}")


def _open_store(run_directory: Path) -> RunArtifactStore:
    directory = Path(run_directory).resolve()
    if directory.parent.parent == directory.parent:
        raise LA1ArtifactError("run_directory is invalid")
    return RunArtifactStore(
        output_directory=directory.parent.parent,
        experiment_id=directory.parent.name,
        run_id=directory.name,
        run_directory=directory,
        schemas=LA1_ARTIFACT_SCHEMAS,
    )


def _validate_config(
    config: Mapping[str, Any],
    directory: Path,
) -> None:
    try:
        Draft202012Validator(LA1_ARTIFACT_SCHEMAS.config).validate(dict(config))
    except ValidationError as error:
        raise LA1ArtifactIntegrityError(
            "persisted LA1 config schema is invalid"
        ) from error
    if (
        config["experiment_id"] != directory.parent.name
        or config["run_id"] != directory.name
    ):
        raise LA1ArtifactIntegrityError(
            "persisted LA1 config identity does not match directory"
        )
    scenario = config["scenario"]
    if config["scenario_parameters"] != _scenario_parameters(scenario):
        raise LA1ArtifactIntegrityError(
            "persisted LA1 scenario parameters do not replay"
        )
    expected_fixture = _sha256(_fixture_projection(scenario, config["run_id"]))
    if config["fixture_sha256"] != expected_fixture:
        raise LA1ArtifactIntegrityError("persisted LA1 fixture hash does not replay")
    if config["source_sha256"] != _source_hashes():
        raise LA1ArtifactIntegrityError(
            "persisted LA1 source hashes do not match runtime"
        )


def prepare_la1_run(
    *,
    output_directory: str | Path,
    run_id: str,
    scenario: str,
) -> Path:
    """Create a write-once LA1 run and persist its frozen public config."""

    if scenario not in SCENARIOS:
        raise LA1ArtifactError(f"unknown LA1 scenario: {scenario}")
    store = RunArtifactStore.create(
        output_directory,
        EXPERIMENT_ID,
        run_id,
        schemas=LA1_ARTIFACT_SCHEMAS,
    )
    fixture_projection = _fixture_projection(scenario, run_id)
    store.write_config(
        {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "experiment_id": EXPERIMENT_ID,
            "run_id": run_id,
            "scenario": scenario,
            "runner_version": RUNNER_VERSION,
            "run_budget": {"tokens": 100.0},
            "scenario_parameters": _scenario_parameters(scenario),
            "fixture_sha256": _sha256(fixture_projection),
            "source_sha256": _source_hashes(),
            "environment": _environment(),
            "exclusion_policy": {
                "failed_execution_retained": True,
                "invalid_proposals_count_as_system_outcomes": True,
                "silent_exclusion_allowed": False,
            },
        }
    )
    config_sha256 = _file_sha256(store.run_directory / "config.json")
    lock_path = store.write_artifact(
        "config_lock.json",
        {
            "schema_version": 1,
            "experiment_id": EXPERIMENT_ID,
            "run_id": run_id,
            "runner_version": RUNNER_VERSION,
            "config_sha256": config_sha256,
        },
    )
    store.write_artifact(
        "config_seal.json",
        {
            "schema_version": 1,
            "config_lock_sha256": _file_sha256(lock_path),
        },
    )
    return store.run_directory


def _verify_prepared_config(directory: Path) -> None:
    lock_path = directory / "artifacts" / "config_lock.json"
    seal_path = directory / "artifacts" / "config_seal.json"
    if (
        not lock_path.is_file()
        or not seal_path.is_file()
        or lock_path.is_symlink()
        or seal_path.is_symlink()
    ):
        raise LA1ArtifactIntegrityError("prepared config lock or seal is invalid")
    lock = _read_json(lock_path)
    seal = _read_json(seal_path)
    if seal.get("config_lock_sha256") != _file_sha256(lock_path):
        raise LA1ArtifactIntegrityError("prepared config lock hash mismatch")
    if (
        lock.get("schema_version") != 1
        or lock.get("experiment_id") != EXPERIMENT_ID
        or lock.get("run_id") != directory.name
        or lock.get("runner_version") != RUNNER_VERSION
        or lock.get("config_sha256") != _file_sha256(directory / "config.json")
    ):
        raise LA1ArtifactIntegrityError("prepared config hash mismatch")


def _event_from_dict(value: Mapping[str, Any]) -> HarnessRuntimeEvent:
    try:
        return HarnessRuntimeEvent(
            event_id=value["event_id"],
            event_type=value["event_type"],
            event_schema_version=value["event_schema_version"],
            public_state_revision=value["public_state_revision"],
            causal_parent_ids=tuple(value["causal_parent_ids"]),
            payload=value["payload"],
            payload_sha256=value["payload_sha256"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise LA1ArtifactIntegrityError(
            "persisted public event contract is invalid"
        ) from error


def _execute_scenario(config: Mapping[str, Any]) -> _ScenarioExecution:
    scenario = config["scenario"]
    run_id = config["run_id"]
    if scenario == "success":
        inputs = _success_inputs(run_id)
        result = run_gate_episode(**inputs)
        replayed = replay_gate_episode(events=result.events, **inputs)
        if replayed.terminal_projection_sha256 != result.terminal_projection_sha256:
            raise LA1ArtifactIntegrityError(
                "success scenario did not replay before persistence"
            )
        return _ScenarioExecution(
            events=result.events,
            organization_snapshot=result.organization_snapshot,
            ledger_totals=result.ledger_totals,
            terminal_projection_sha256=result.terminal_projection_sha256,
            checkpoint=None,
            extra_artifacts={},
        )
    if scenario == "failure_recovery":
        inputs = _failure_inputs(run_id)
        result = run_failure_reorganization(**inputs)
        split = (
            next(
                index
                for index, event in enumerate(result.events)
                if event.event_type == "failure_settlement"
            )
            + 1
        )
        checkpoint = create_failure_reorganization_checkpoint(
            candidates=inputs["candidates"],
            admission_policy=inputs["admission_policy"],
            multi_policy=inputs["multi_policy"],
            run_budget=inputs["run_budget"],
            events=result.events[:split],
        )
        resumed = resume_failure_reorganization(
            checkpoint=checkpoint,
            candidates=inputs["candidates"],
            admission_policy=inputs["admission_policy"],
            multi_policy=inputs["multi_policy"],
            run_budget=inputs["run_budget"],
            suffix_events=result.events[split:],
        )
        replayed = replay_failure_reorganization(
            candidates=inputs["candidates"],
            admission_policy=inputs["admission_policy"],
            multi_policy=inputs["multi_policy"],
            run_budget=inputs["run_budget"],
            events=result.events,
        )
        if resumed != replayed:
            raise LA1ArtifactIntegrityError(
                "failure checkpoint resume differs from full replay"
            )
        return _ScenarioExecution(
            events=result.events,
            organization_snapshot=result.organization_snapshot,
            ledger_totals=result.ledger_totals,
            terminal_projection_sha256=result.terminal_projection_sha256,
            checkpoint=checkpoint,
            extra_artifacts={},
        )
    if scenario == "governance_paths":
        result = run_governance_evidence(run_id)
        return _ScenarioExecution(
            events=result.events,
            organization_snapshot=result.organization_snapshot,
            ledger_totals=result.ledger_totals,
            terminal_projection_sha256=result.terminal_projection_sha256,
            checkpoint=None,
            extra_artifacts={"governance_paths.json": result.artifact},
        )
    raise LA1ArtifactError(f"unknown persisted scenario: {scenario}")


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": (numerator / denominator if denominator else None),
        "status": "measured" if denominator else "not_applicable",
    }


def _admission_rejections(
    events: tuple[HarnessRuntimeEvent, ...],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    decision_count = 0
    for event in events:
        result = event.payload.get("result")
        if not isinstance(result, Mapping):
            continue
        decisions = result.get("decisions", ())
        if not isinstance(decisions, (tuple, list)):
            continue
        for decision in decisions:
            if isinstance(decision, Mapping):
                decision_count += 1
            if isinstance(decision, Mapping) and decision.get("status") == "rejected":
                reason = str(decision.get("reason") or "unspecified")
                counts[reason] = counts.get(reason, 0) + 1
    rejected_count = sum(counts.values())
    return {
        "decision_denominator": decision_count,
        "rejected_decisions": rejected_count,
        "rejection_rate": (rejected_count / decision_count if decision_count else None),
        "by_reason": dict(sorted(counts.items())),
        "status": "measured" if decision_count else "not_applicable",
    }


def _illegal_rejection(
    events: tuple[HarnessRuntimeEvent, ...],
) -> dict[str, Any]:
    illegal_reasons = {
        "invalid_bid",
        "action_not_allowed",
        "risk_hard_stop",
        "run_finalized",
    }
    attempts: list[str] = []
    for event in events:
        result = event.payload.get("result")
        if not isinstance(result, Mapping):
            continue
        for decision in result.get("decisions", ()):
            if (
                isinstance(decision, Mapping)
                and decision.get("status") == "rejected"
                and decision.get("reason") in illegal_reasons
            ):
                attempts.append(str(decision["bid_id"]))
    no_side_effect = sum(
        not any(
            bid_id in event.event_id
            and (
                event.event_type.endswith("_commitment")
                or "resource_grant" in event.event_type
            )
            for event in events
        )
        for bid_id in attempts
    )
    return _ratio(no_side_effect, len(attempts))


def _transition_statuses(
    events: tuple[HarnessRuntimeEvent, ...],
) -> tuple[str, ...]:
    statuses: list[str] = []
    for event in events:
        transition = event.payload.get("transition")
        if isinstance(transition, Mapping):
            next_status = transition.get("next_status")
            if isinstance(next_status, str):
                statuses.append(next_status)
    return tuple(statuses)


def _communication(
    events: tuple[HarnessRuntimeEvent, ...],
    organization_snapshot: OrganizationSnapshot,
) -> dict[str, Any]:
    messages = 0
    transferred = 0
    resource_cost: dict[str, float] = {}
    for event in events:
        delivery = event.payload.get("delivery")
        if not isinstance(delivery, Mapping):
            continue
        messages += int(delivery["message_count"])
        transferred += int(delivery["payload_size_bytes"])
        for item in delivery["resource_cost"]:
            resource_type = str(item["resource_type"])
            resource_cost[resource_type] = resource_cost.get(
                resource_type, 0.0
            ) + float(item["amount"])
    accepted = sum(
        float(item.accepted_contribution)
        for item in organization_snapshot.agent_cost_contributions
    )
    return {
        "messages": messages,
        "bytes": transferred,
        "resource_cost": dict(sorted(resource_cost.items())),
        "accepted_contribution_denominator": accepted,
        "cost_per_accepted_contribution": {
            key: value / accepted for key, value in sorted(resource_cost.items())
        }
        if accepted
        else {},
        "status": "measured" if accepted else "not_applicable",
    }


def _refusal_recovery(
    events: tuple[HarnessRuntimeEvent, ...],
) -> dict[str, Any]:
    refusals = tuple(
        (index, event)
        for index, event in enumerate(events)
        if "refusal" in event.event_type
    )
    recovered = 0
    for refusal_index, refusal_event in refusals:
        refusal = refusal_event.payload.get("refusal")
        if not isinstance(refusal, Mapping):
            continue
        refusing_agent = refusal.get("agent_id")
        if any(
            isinstance(event.payload.get("commitment"), Mapping)
            and event.payload["commitment"].get("agent_id") != refusing_agent
            for event in events[refusal_index + 1 :]
        ):
            recovered += 1
    return _ratio(recovered, len(refusals))


def _state_update_provenance(
    events: tuple[HarnessRuntimeEvent, ...],
) -> dict[str, Any]:
    updates = tuple(
        event
        for event in events
        if event.event_type.startswith("local_state_")
        and "transition" in event.event_type
    )
    complete = 0
    for event in updates:
        transition = event.payload.get("local_state_transition")
        if not isinstance(transition, Mapping):
            continue
        sources = tuple(
            value
            for key, value in transition.items()
            if key.startswith("source_") and isinstance(value, str) and value
        )
        if event.causal_parent_ids and sources:
            complete += 1
    return _ratio(complete, len(updates))


def _native_state_update_provenance(
    native_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure state provenance inside the two sealed governance traces."""

    complete = 0
    denominator = 0
    trace_count = 0
    for trace_name in ("rejected_events", "disputed_events"):
        raw_trace = native_artifact.get(trace_name)
        if not isinstance(raw_trace, (list, tuple)):
            continue
        trace_count += 1
        next_version_by_agent: dict[str, int] = {}
        for raw_event in raw_trace:
            if (
                not isinstance(raw_event, Mapping)
                or raw_event.get("event_type") != "local_state_update"
            ):
                continue
            denominator += 1
            payload = raw_event.get("payload")
            update = (
                payload.get("local_state_update")
                if isinstance(payload, Mapping)
                else None
            )
            parents = raw_event.get("causal_parent_ids")
            if (
                not isinstance(update, Mapping)
                or not isinstance(parents, (list, tuple))
                or not parents
                or not all(isinstance(parent, str) and parent for parent in parents)
            ):
                continue
            agent_id = update.get("agent_id")
            previous = update.get("previous_state_version")
            next_version = update.get("next_state_version")
            source_window = update.get("source_event_window")
            before_hash = update.get("before_hash")
            after_hash = update.get("after_hash")
            if (
                not isinstance(agent_id, str)
                or not agent_id
                or not isinstance(previous, int)
                or isinstance(previous, bool)
                or not isinstance(next_version, int)
                or isinstance(next_version, bool)
                or next_version != previous + 1
                or (
                    agent_id in next_version_by_agent
                    and previous != next_version_by_agent[agent_id]
                )
                or not isinstance(source_window, (list, tuple))
                or not source_window
                or not all(
                    isinstance(source, str) and source for source in source_window
                )
                or not set(source_window).issubset(set(parents))
                or not isinstance(before_hash, str)
                or len(before_hash) != 64
                or not isinstance(after_hash, str)
                or len(after_hash) != 64
                or before_hash == after_hash
            ):
                continue
            next_version_by_agent[agent_id] = next_version
            complete += 1
    return {
        **_ratio(complete, denominator),
        "trace_count": trace_count,
    }


def _augment_governance_metrics(
    metrics: dict[str, Any],
    *,
    wrapper_events: tuple[HarnessRuntimeEvent, ...],
    native_artifact: Mapping[str, Any],
) -> None:
    metrics["metric_definitions"]["native_state_update_provenance"] = (
        "governance native local-state updates with continuous versions, "
        "hash-bound state transition, and a non-empty source window contained "
        "in causal parents / all governance native local-state updates"
    )
    metrics["canonical_path_coverage"] = dict(wrapper_events[-1].payload["coverage"])
    metrics["native_state_update_provenance"] = _native_state_update_provenance(
        native_artifact
    )
    native_events = tuple(
        event
        for key in ("rejected_events", "disputed_events")
        for event in native_artifact[key]
    )
    native_types = tuple(str(event["event_type"]) for event in native_events)
    metrics["cost_vector"].update(
        {
            "tool_calls": sum(
                event_type in {"action", "revalidation_evidence"}
                for event_type in native_types
            ),
            "state_update_calls": sum(
                event_type == "local_state_update" for event_type in native_types
            ),
            "verifier_calls": sum(
                event_type in {"verifier_decision", "revalidation_decision"}
                for event_type in native_types
            ),
            "deterministic_check_calls": 4,
            "retry_count": 1,
        }
    )


def _residual_cycles(
    events: tuple[HarnessRuntimeEvent, ...],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        residual = event.payload.get("residual")
        if not isinstance(residual, Mapping):
            continue
        requirements = residual.get("requirements", ())
        status_by_requirement = {
            str(item["requirement_id"]): str(item["status"])
            for item in requirements
            if isinstance(item, Mapping)
        }
        result.append(
            {
                "event_id": event.event_id,
                "revision": int(residual["revision"]),
                "complete": bool(residual["complete"]),
                "status_by_requirement": status_by_requirement,
            }
        )
    return result


def _organization_stats(
    snapshot: OrganizationSnapshot,
) -> dict[str, Any]:
    return {
        "active_agents": len(snapshot.active_agents),
        "commitment_links": len(snapshot.requirement_commitments),
        "communication_edges": len(snapshot.communication_edges),
        "refusal_count": sum(item.count for item in snapshot.refusal_distribution),
        "duplicate_count": sum(item.count for item in snapshot.duplicate_distribution),
        "accepted_contribution": sum(
            float(item.accepted_contribution)
            for item in snapshot.agent_cost_contributions
        ),
        "central_role_bindings": len(snapshot.central_preset_info.role_bindings),
        "central_route_refs": len(snapshot.central_preset_info.route_refs),
        "central_topology_refs": len(snapshot.central_preset_info.topology_refs),
    }


def summarize_la1_run(
    *,
    scenario: str,
    events: tuple[HarnessRuntimeEvent, ...],
    organization_snapshot: OrganizationSnapshot,
    ledger_totals: Mapping[str, Mapping[str, str]],
    terminal_projection_sha256: str,
    run_budget: Mapping[str, float],
    wall_time_ms: float,
    cpu_time_ms: float,
    deterministic_check_calls: int,
) -> dict[str, Any]:
    """Aggregate the frozen LA1 §7.4 metrics from one public event stream."""

    materialized = tuple(events)
    rejections = _admission_rejections(materialized)
    first_commitment = next(
        (
            index + 1
            for index, event in enumerate(materialized)
            if event.event_type.endswith("_commitment")
        ),
        None,
    )
    communication = _communication(materialized, organization_snapshot)
    transitions = _transition_statuses(materialized)
    action_events = tuple(
        event
        for event in materialized
        if event.event_type
        in {
            "gate_action",
            "failure_execution",
            "takeover_execution",
        }
    )
    duplicate_count = sum(
        item.count for item in organization_snapshot.duplicate_distribution
    )
    ledger_checks: dict[str, dict[str, Any]] = {}
    all_conserved = True
    for resource_type, total in sorted(ledger_totals.items()):
        accounted = sum(
            Decimal(total[key])
            for key in ("shared_pool", "escrow", "reserved", "spent")
        )
        expected = Decimal(str(run_budget[resource_type]))
        conserved = accounted == expected
        all_conserved = all_conserved and conserved
        ledger_checks[resource_type] = {
            "accounted": str(accounted),
            "expected": str(expected),
            "conserved": conserved,
        }
    state_provenance = _state_update_provenance(materialized)
    state_update_calls = state_provenance["denominator"]
    verifier_calls = sum("verifier" in event.event_type for event in materialized)
    reorganization_count = sum(
        event.event_type == "failure_readmission" for event in materialized
    )
    completed = sum(status == "completed" for status in transitions)
    cancelled = sum(status in {"cancelled", "failed"} for status in transitions)
    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "scenario": scenario,
        "run_validity": "valid",
        "metric_definitions": dict(_METRIC_DEFINITIONS),
        "contract_validity": _ratio(len(materialized), len(materialized)),
        "admission_rejection_by_reason": rejections,
        "illegal_rejection": _illegal_rejection(materialized),
        "time_to_first_commitment": {
            "value": first_commitment,
            "unit": "public_events",
            "origin": "first persisted public event",
        },
        "duplicate_effort": {
            "count": duplicate_count,
            "action_denominator": len(action_events),
            "rate": (duplicate_count / len(action_events) if action_events else None),
        },
        "refusal_recovery": _refusal_recovery(materialized),
        "communication": communication,
        "state_update_provenance": state_provenance,
        "public_terminal_hash": terminal_projection_sha256,
        "ledger_conservation": {
            "conserved": all_conserved,
            "by_resource": ledger_checks,
        },
        "residual_over_cycles": _residual_cycles(materialized),
        "reorganization_count": reorganization_count,
        "completion_recovery_cycles": {
            "completed_commitments": completed,
            "failed_or_cancelled_commitments": cancelled,
            "recovery_cycles": reorganization_count,
            "total_commitment_cycles": completed + cancelled,
        },
        "organization_snapshot_stats": _organization_stats(organization_snapshot),
        "cost_vector": {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": len(action_events),
            "wall_time_ms": wall_time_ms,
            "cpu_time_ms": cpu_time_ms,
            "bytes_transferred": communication["bytes"],
            "communication_messages": communication["messages"],
            "communication_tokens": communication["resource_cost"].get(
                "tokens",
                0,
            ),
            "state_update_calls": state_update_calls,
            "verifier_calls": verifier_calls,
            "deterministic_check_calls": deterministic_check_calls,
            "judge_calls": 0,
            "human_escalations": 0,
            "retry_count": reorganization_count,
        },
    }
    return metrics


def _artifact_hashes(store: RunArtifactStore) -> dict[str, str]:
    return _collect_artifact_hashes(store.artifacts_directory)


def _collect_artifact_hashes(artifacts_directory: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(artifacts_directory.iterdir()):
        if path.is_symlink():
            raise LA1ArtifactIntegrityError(
                f"artifact cannot be a symbolic link: {path.name}"
            )
        if not path.is_file():
            raise LA1ArtifactIntegrityError(
                f"artifact must be a regular file: {path.name}"
            )
        hashes[path.name] = _file_sha256(path)
    return hashes


def _summary_markdown(metrics: Mapping[str, Any]) -> str:
    return (
        "# LA1 scripted run\n\n"
        f"- Scenario: `{metrics['scenario']}`\n"
        f"- Run validity: `{metrics['run_validity']}`\n"
        f"- Public terminal hash: "
        f"`{metrics.get('public_terminal_hash', 'unavailable')}`\n"
        "- Claim boundary: scripted engineering evidence only; this run does "
        "not support real-model differentiation, O1/O2, Field increment, or "
        "self-evolution.\n"
    )


def _failure_metrics(
    *,
    scenario: str,
    error: Exception,
    wall_time_ms: float,
    cpu_time_ms: float,
) -> dict[str, Any]:
    return {
        "schema_version": METRICS_SCHEMA_VERSION,
        "scenario": scenario,
        "run_validity": "invalid-run",
        "metric_definitions": dict(_METRIC_DEFINITIONS),
        "failure": {
            "error_type": type(error).__name__,
            "message": str(error),
            "excluded_from_denominator": False,
        },
        "cost_vector": {
            **{key: 0 for key in _COST_VECTOR_FIELDS},
            "wall_time_ms": wall_time_ms,
            "cpu_time_ms": cpu_time_ms,
        },
    }


def _failure_summary_markdown(
    *,
    scenario: str,
    error: Exception,
) -> str:
    return (
        "# LA1 scripted run\n\n"
        f"- Scenario: `{scenario}`\n"
        "- Run validity: `invalid-run`\n"
        f"- Failure: `{type(error).__name__}`\n"
        "- Claim boundary: retained runner failure; excluded from scientific "
        "support but not silently removed from the run ledger.\n"
    )


def _failure_summary_from_payload(
    *,
    scenario: str,
    failure: Mapping[str, Any],
) -> str:
    return (
        "# LA1 scripted run\n\n"
        f"- Scenario: `{scenario}`\n"
        "- Run validity: `invalid-run`\n"
        f"- Failure: `{failure['error_type']}`\n"
        "- Claim boundary: retained runner failure; excluded from scientific "
        "support but not silently removed from the run ledger.\n"
    )


def _failure_summary_artifact(
    *,
    scenario: str,
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "authority": "authoritative",
        "scenario": scenario,
        "run_validity": "invalid-run",
        "markdown": _failure_summary_from_payload(
            scenario=scenario,
            failure=failure,
        ),
    }


def _persist_post_metrics_failure(
    *,
    store: RunArtifactStore,
    scenario: str,
    failure_event: HarnessRuntimeEvent,
    error: Exception,
    wall_time_ms: float,
    cpu_time_ms: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    partial_metrics_path = store.run_directory / "metrics.json"
    partial_metrics = store.read_metrics()
    if partial_metrics.get("run_validity") != "valid" or "failure" in partial_metrics:
        raise LA1ArtifactIntegrityError(
            "existing post-metrics artifact is not a valid partial result"
        )
    partial_metrics_ref = {
        "authoritative": False,
        "path": "metrics.json",
        "sha256": _file_sha256(partial_metrics_path),
    }
    failure_record = {
        "schema_version": 1,
        "event_id": failure_event.event_id,
        "error_type": type(error).__name__,
        "message": str(error),
        "partial_metrics": partial_metrics_ref,
        "authoritative_metrics_path": ("artifacts/failure_metrics.json"),
    }
    failure_record_path = store.write_artifact(
        "failure.json",
        failure_record,
    )
    failure_metrics = _failure_metrics(
        scenario=scenario,
        error=error,
        wall_time_ms=wall_time_ms,
        cpu_time_ms=cpu_time_ms,
    )
    failure_metrics["partial_metrics"] = partial_metrics_ref
    failure_metrics["failure_record"] = {
        "path": "artifacts/failure.json",
        "sha256": _file_sha256(failure_record_path),
    }
    failure_summary_path = store.write_artifact(
        "failure_summary.json",
        _failure_summary_artifact(
            scenario=scenario,
            failure=dict(failure_event.payload),
        ),
    )
    failure_metrics["authoritative_summary"] = {
        "path": "artifacts/failure_summary.json",
        "sha256": _file_sha256(failure_summary_path),
    }
    partial_summary_path = store.run_directory / "summary.md"
    if partial_summary_path.exists():
        failure_metrics["partial_summary"] = {
            "authoritative": False,
            "path": "summary.md",
            "sha256": _file_sha256(partial_summary_path),
        }
    failure_metrics["artifact_sha256"] = _collect_artifact_hashes(
        store.artifacts_directory
    )
    authoritative_path = store.write_artifact(
        "failure_metrics.json",
        failure_metrics,
    )
    final_state = {
        "scenario": scenario,
        "status": "failed",
        "failure_sha256": _sha256(dict(failure_event.payload)),
        "authoritative_metrics": {
            "path": "artifacts/failure_metrics.json",
            "sha256": _file_sha256(authoritative_path),
        },
        "partial_metrics": partial_metrics_ref,
        "failure_record": failure_metrics["failure_record"],
        "authoritative_summary": failure_metrics["authoritative_summary"],
        "artifact_sha256": failure_metrics["artifact_sha256"],
    }
    if "partial_summary" in failure_metrics:
        final_state["partial_summary"] = failure_metrics["partial_summary"]
    return failure_metrics, final_state


def _append_runner_failure_event(
    store: RunArtifactStore,
    *,
    run_id: str,
    error: Exception,
) -> HarnessRuntimeEvent:
    existing = store.read_events()
    payload = {
        "error_type": type(error).__name__,
        "message": str(error),
    }
    event = HarnessRuntimeEvent(
        event_id=f"la1-runner-failure-{run_id}-{len(existing)}",
        event_type="la1_runner_failure",
        event_schema_version=1,
        public_state_revision=len(existing),
        causal_parent_ids=((str(existing[-1]["event_id"]),) if existing else ()),
        payload=payload,
        payload_sha256=_sha256(payload),
    )
    store.append_event(event)
    return event


def execute_la1_run(run_directory: str | Path) -> LA1RunExecution:
    """Execute a prepared run and seal completed or failed evidence."""

    requested = Path(run_directory).expanduser()
    if requested.is_symlink():
        raise LA1ArtifactIntegrityError("LA1 run directory cannot be a symbolic link")
    directory = requested.resolve()
    store = _open_store(directory)
    if (directory / "finalization.json").exists():
        raise RunFinalizedError("run is finalized and cannot be mutated")
    config = store.read_config()
    _verify_prepared_config(directory)
    _validate_config(config, directory)
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    try:
        scenario_result = _execute_scenario(config)
        for event in scenario_result.events:
            store.append_event(event)
        store.write_artifact(
            "organization_snapshot.json",
            scenario_result.organization_snapshot,
        )
        if scenario_result.checkpoint is not None:
            store.write_artifact(
                "failure_checkpoint.json",
                scenario_result.checkpoint,
            )
        for filename, artifact in sorted(scenario_result.extra_artifacts.items()):
            store.write_artifact(filename, artifact)
        wall_time_ms = (time.perf_counter() - start_wall) * 1000
        cpu_time_ms = (time.process_time() - start_cpu) * 1000
        metrics = summarize_la1_run(
            scenario=config["scenario"],
            events=scenario_result.events,
            organization_snapshot=scenario_result.organization_snapshot,
            ledger_totals=scenario_result.ledger_totals,
            terminal_projection_sha256=(scenario_result.terminal_projection_sha256),
            run_budget=config["run_budget"],
            wall_time_ms=wall_time_ms,
            cpu_time_ms=cpu_time_ms,
            deterministic_check_calls=1,
        )
        if config["scenario"] == "governance_paths":
            _augment_governance_metrics(
                metrics,
                wrapper_events=scenario_result.events,
                native_artifact=scenario_result.extra_artifacts[
                    "governance_paths.json"
                ],
            )
        metrics["artifact_sha256"] = _artifact_hashes(store)
        summary_markdown = _summary_markdown(metrics)
        store.write_metrics(metrics)
        store.write_summary(summary_markdown)
        final_state = {
            "scenario": config["scenario"],
            "status": "completed",
            "terminal_projection_sha256": (scenario_result.terminal_projection_sha256),
            "organization_snapshot_sha256": (
                scenario_result.organization_snapshot.snapshot_hash
            ),
            "ledger_totals": _json_ready(scenario_result.ledger_totals),
            "artifact_sha256": metrics["artifact_sha256"],
        }
        store.finalize(
            status=RunTerminalStatus.COMPLETED,
            reason=_COMPLETED_FINALIZATION_REASON,
            final_state=final_state,
        )
        return LA1RunExecution(
            run_directory=directory,
            scenario=config["scenario"],
            status="completed",
            events=scenario_result.events,
            organization_snapshot=scenario_result.organization_snapshot,
            ledger_totals=scenario_result.ledger_totals,
            terminal_projection_sha256=(scenario_result.terminal_projection_sha256),
            metrics=metrics,
        )
    except Exception as error:
        if isinstance(error, RunFinalizedError):
            raise
        wall_time_ms = (time.perf_counter() - start_wall) * 1000
        cpu_time_ms = (time.process_time() - start_cpu) * 1000
        try:
            failure_event = _append_runner_failure_event(
                store,
                run_id=config["run_id"],
                error=error,
            )
            metrics_path = directory / "metrics.json"
            if metrics_path.exists():
                metrics, failure_state = _persist_post_metrics_failure(
                    store=store,
                    scenario=config["scenario"],
                    failure_event=failure_event,
                    error=error,
                    wall_time_ms=wall_time_ms,
                    cpu_time_ms=cpu_time_ms,
                )
            else:
                store.write_artifact(
                    "failure_record.json",
                    {
                        "schema_version": 1,
                        "event_id": failure_event.event_id,
                        "error_type": type(error).__name__,
                        "message": str(error),
                    },
                )
                metrics = _failure_metrics(
                    scenario=config["scenario"],
                    error=error,
                    wall_time_ms=wall_time_ms,
                    cpu_time_ms=cpu_time_ms,
                )
                metrics["artifact_sha256"] = _collect_artifact_hashes(
                    store.artifacts_directory
                )
                store.write_metrics(metrics)
                failure_state = {
                    "scenario": config["scenario"],
                    "status": "failed",
                    "failure_sha256": _sha256(dict(failure_event.payload)),
                    "artifact_sha256": metrics.get(
                        "artifact_sha256",
                        {},
                    ),
                }
            if not (directory / "summary.md").exists():
                store.write_summary(
                    _failure_summary_markdown(
                        scenario=config["scenario"],
                        error=error,
                    )
                )
            store.finalize(
                status=RunTerminalStatus.FAILED,
                reason=_FAILED_FINALIZATION_REASON,
                final_state=failure_state,
            )
        except Exception as persistence_error:
            raise LA1RunExecutionError(
                f"{error}; failed-run sealing also failed: {persistence_error}",
                directory,
            ) from error
        raise LA1RunExecutionError(str(error), directory) from error


def _verify_standard_seal(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, Any], tuple[HarnessRuntimeEvent, ...]]:
    finalization_path = directory / "finalization.json"
    if finalization_path.is_symlink() or not finalization_path.is_file():
        raise LA1ArtifactIntegrityError(
            "finalization must be a regular file, not a symbolic link"
        )
    finalization = _read_json(finalization_path)
    expected_finalization_keys = {
        "schema_version",
        "experiment_id",
        "run_id",
        "status",
        "reason",
        "event_count",
        "file_sha256",
        "final_state_sha256",
    }
    expected_reasons = {
        RunTerminalStatus.COMPLETED.value: _COMPLETED_FINALIZATION_REASON,
        RunTerminalStatus.FAILED.value: _FAILED_FINALIZATION_REASON,
    }
    if (
        set(finalization) != expected_finalization_keys
        or finalization.get("schema_version") != 1
        or finalization.get("experiment_id") != EXPERIMENT_ID
        or finalization.get("run_id") != directory.name
        or finalization.get("status") not in expected_reasons
        or finalization.get("reason")
        != expected_reasons.get(finalization.get("status"))
    ):
        raise LA1ArtifactIntegrityError("finalization contract is invalid")
    file_hashes = finalization.get("file_sha256")
    if not isinstance(file_hashes, Mapping):
        raise LA1ArtifactIntegrityError("finalization file hashes are invalid")
    required = {"config.json", "events.jsonl", "metrics.json", "summary.md"}
    if set(file_hashes) != required:
        raise LA1ArtifactIntegrityError("sealed file set mismatch")
    for filename, digest in file_hashes.items():
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            raise LA1ArtifactIntegrityError(
                f"sealed file cannot be a symbolic link: {filename}"
            )
        if _file_sha256(path) != digest:
            raise LA1ArtifactIntegrityError(f"sealed file hash mismatch: {filename}")
    metrics = _read_json(directory / "metrics.json")
    events = tuple(
        _event_from_dict(value) for value in _open_store(directory).read_events()
    )
    if finalization.get("event_count") != len(events):
        raise LA1ArtifactIntegrityError("sealed event count mismatch")
    return finalization, metrics, events


def _verify_failure_metrics_contract(
    *,
    metrics: Mapping[str, Any],
    scenario: str,
    failure_payload: Mapping[str, Any],
    post_metrics: bool,
) -> None:
    expected_keys = {
        "schema_version",
        "scenario",
        "run_validity",
        "metric_definitions",
        "failure",
        "cost_vector",
        "artifact_sha256",
    }
    if post_metrics:
        expected_keys.update(
            {
                "partial_metrics",
                "failure_record",
                "authoritative_summary",
            }
        )
        if "partial_summary" in metrics:
            expected_keys.add("partial_summary")
    expected_failure = {
        "error_type": failure_payload["error_type"],
        "message": failure_payload["message"],
        "excluded_from_denominator": False,
    }
    cost = metrics.get("cost_vector")
    if (
        set(metrics) != expected_keys
        or metrics.get("schema_version") != METRICS_SCHEMA_VERSION
        or metrics.get("scenario") != scenario
        or metrics.get("run_validity") != "invalid-run"
        or metrics.get("metric_definitions") != dict(_METRIC_DEFINITIONS)
        or metrics.get("failure") != expected_failure
        or not isinstance(cost, Mapping)
        or set(cost) != set(_COST_VECTOR_FIELDS)
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            for value in cost.values()
        )
        or not isinstance(metrics.get("artifact_sha256"), Mapping)
    ):
        prefix = "authoritative " if post_metrics else ""
        raise LA1ArtifactIntegrityError(f"{prefix}failure metrics contract is invalid")


def _verify_artifacts(
    directory: Path,
    metrics: Mapping[str, Any],
) -> None:
    expected = metrics.get("artifact_sha256", {})
    if not isinstance(expected, Mapping):
        raise LA1ArtifactIntegrityError("artifact hash manifest is invalid")
    actual = _collect_artifact_hashes(directory / "artifacts")
    actual_names = set(actual)
    if actual_names != set(expected):
        raise LA1ArtifactIntegrityError("sealed artifact file set mismatch")
    for filename, digest in expected.items():
        if actual[filename] != digest:
            raise LA1ArtifactIntegrityError(
                f"sealed artifact hash mismatch: {filename}"
            )


def _verify_post_metrics_failure(
    *,
    directory: Path,
    config: Mapping[str, Any],
    finalization: Mapping[str, Any],
    events: tuple[HarnessRuntimeEvent, ...],
) -> dict[str, Any]:
    authoritative_path = directory / "artifacts" / "failure_metrics.json"
    if authoritative_path.is_symlink() or not authoritative_path.is_file():
        raise LA1ArtifactIntegrityError(
            "authoritative failure metrics must be a regular file"
        )
    authoritative_sha256 = _file_sha256(authoritative_path)
    authoritative = _read_json(authoritative_path)
    if (
        authoritative.get("schema_version") != METRICS_SCHEMA_VERSION
        or authoritative.get("scenario") != config["scenario"]
        or authoritative.get("run_validity") != "invalid-run"
        or "public_terminal_hash" in authoritative
        or not isinstance(authoritative.get("failure"), Mapping)
        or set(authoritative.get("cost_vector", {})) != set(_COST_VECTOR_FIELDS)
    ):
        raise LA1ArtifactIntegrityError("authoritative failure metrics are invalid")
    if (
        not events
        or events[-1].event_type != "la1_runner_failure"
        or _sha256(dict(events[-1].payload)) != events[-1].payload_sha256
    ):
        raise LA1ArtifactIntegrityError("failed run retention contract is invalid")
    failure_payload = dict(events[-1].payload)
    _verify_failure_metrics_contract(
        metrics=authoritative,
        scenario=config["scenario"],
        failure_payload=failure_payload,
        post_metrics=True,
    )
    if authoritative["failure"] != {
        "error_type": failure_payload["error_type"],
        "message": failure_payload["message"],
        "excluded_from_denominator": False,
    }:
        raise LA1ArtifactIntegrityError(
            "authoritative failure metrics do not match failure event"
        )
    partial_ref = authoritative.get("partial_metrics")
    if not isinstance(partial_ref, Mapping) or dict(partial_ref) != {
        "authoritative": False,
        "path": "metrics.json",
        "sha256": _file_sha256(directory / "metrics.json"),
    }:
        raise LA1ArtifactIntegrityError("partial metrics reference is invalid")
    partial_metrics = _read_json(directory / "metrics.json")
    if partial_metrics.get("run_validity") != "valid" or "failure" in partial_metrics:
        raise LA1ArtifactIntegrityError("partial metrics authority boundary is invalid")
    authoritative_summary_ref = authoritative.get("authoritative_summary")
    authoritative_summary_path = directory / "artifacts" / "failure_summary.json"
    if (
        not isinstance(authoritative_summary_ref, Mapping)
        or dict(authoritative_summary_ref)
        != {
            "path": "artifacts/failure_summary.json",
            "sha256": _file_sha256(authoritative_summary_path),
        }
        or _read_json(authoritative_summary_path)
        != _failure_summary_artifact(
            scenario=config["scenario"],
            failure=failure_payload,
        )
    ):
        raise LA1ArtifactIntegrityError("authoritative failure summary is invalid")
    summary_path = directory / "summary.md"
    summary = summary_path.read_text(encoding="utf-8")
    partial_summary_ref = authoritative.get("partial_summary")
    if partial_summary_ref is None:
        if summary != _failure_summary_from_payload(
            scenario=config["scenario"],
            failure=failure_payload,
        ):
            raise LA1ArtifactIntegrityError("failed run summary does not replay")
    elif (
        not isinstance(partial_summary_ref, Mapping)
        or dict(partial_summary_ref)
        != {
            "authoritative": False,
            "path": "summary.md",
            "sha256": _file_sha256(summary_path),
        }
        or summary != _summary_markdown(partial_metrics)
    ):
        raise LA1ArtifactIntegrityError("partial summary authority boundary is invalid")
    failure_record_ref = authoritative.get("failure_record")
    failure_record_path = directory / "artifacts" / "failure.json"
    if not isinstance(failure_record_ref, Mapping) or dict(failure_record_ref) != {
        "path": "artifacts/failure.json",
        "sha256": _file_sha256(failure_record_path),
    }:
        raise LA1ArtifactIntegrityError("failure record reference is invalid")
    failure_record = _read_json(failure_record_path)
    if failure_record != {
        "schema_version": 1,
        "event_id": events[-1].event_id,
        "error_type": failure_payload["error_type"],
        "message": failure_payload["message"],
        "partial_metrics": dict(partial_ref),
        "authoritative_metrics_path": ("artifacts/failure_metrics.json"),
    }:
        raise LA1ArtifactIntegrityError("failure record is invalid")
    expected_artifacts = authoritative.get("artifact_sha256")
    if not isinstance(expected_artifacts, Mapping):
        raise LA1ArtifactIntegrityError(
            "authoritative artifact hash manifest is invalid"
        )
    actual_artifacts = _collect_artifact_hashes(directory / "artifacts")
    if set(actual_artifacts) != {
        *expected_artifacts,
        "failure_metrics.json",
    }:
        raise LA1ArtifactIntegrityError("authoritative artifact file set mismatch")
    for filename, digest in expected_artifacts.items():
        if actual_artifacts[filename] != digest:
            raise LA1ArtifactIntegrityError(
                f"authoritative artifact hash mismatch: {filename}"
            )
    final_state = {
        "scenario": config["scenario"],
        "status": "failed",
        "failure_sha256": _sha256(failure_payload),
        "authoritative_metrics": {
            "path": "artifacts/failure_metrics.json",
            "sha256": authoritative_sha256,
        },
        "partial_metrics": dict(partial_ref),
        "failure_record": dict(failure_record_ref),
        "authoritative_summary": dict(authoritative_summary_ref),
        "artifact_sha256": dict(expected_artifacts),
    }
    if partial_summary_ref is not None:
        final_state["partial_summary"] = dict(partial_summary_ref)
    if _sha256(final_state) != finalization.get("final_state_sha256"):
        raise LA1ArtifactIntegrityError("authoritative failure metrics hash mismatch")
    return authoritative


def replay_la1_run(run_directory: str | Path) -> LA1RunExecution:
    """Verify seals and replay one persisted completed or failed LA1 run."""

    requested = Path(run_directory).expanduser()
    if requested.is_symlink():
        raise LA1ArtifactIntegrityError("LA1 run directory cannot be a symbolic link")
    directory = requested.resolve()
    finalization, metrics, events = _verify_standard_seal(directory)
    config = _read_json(directory / "config.json")
    _verify_prepared_config(directory)
    _validate_config(config, directory)
    status = finalization.get("status")
    if status == RunTerminalStatus.FAILED.value:
        authoritative_path = directory / "artifacts" / "failure_metrics.json"
        if authoritative_path.exists() or authoritative_path.is_symlink():
            metrics = _verify_post_metrics_failure(
                directory=directory,
                config=config,
                finalization=finalization,
                events=events,
            )
            return LA1RunExecution(
                run_directory=directory,
                scenario=config["scenario"],
                status="failed",
                events=events,
                organization_snapshot=None,
                ledger_totals={},
                terminal_projection_sha256=None,
                metrics=metrics,
            )
        _verify_artifacts(directory, metrics)
        if (
            not events
            or events[-1].event_type != "la1_runner_failure"
            or _sha256(dict(events[-1].payload)) != events[-1].payload_sha256
        ):
            raise LA1ArtifactIntegrityError("failed run retention contract is invalid")
        failure_payload = dict(events[-1].payload)
        _verify_failure_metrics_contract(
            metrics=metrics,
            scenario=config["scenario"],
            failure_payload=failure_payload,
            post_metrics=False,
        )
        expected_summary = _failure_summary_from_payload(
            scenario=config["scenario"],
            failure=failure_payload,
        )
        if (directory / "summary.md").read_text(encoding="utf-8") != expected_summary:
            raise LA1ArtifactIntegrityError("failed run summary does not replay")
        failure_state = {
            "scenario": config["scenario"],
            "status": "failed",
            "failure_sha256": _sha256(failure_payload),
            "artifact_sha256": metrics.get("artifact_sha256", {}),
        }
        if _sha256(failure_state) != finalization.get("final_state_sha256"):
            raise LA1ArtifactIntegrityError("failed final state hash mismatch")
        return LA1RunExecution(
            run_directory=directory,
            scenario=config["scenario"],
            status="failed",
            events=events,
            organization_snapshot=None,
            ledger_totals={},
            terminal_projection_sha256=None,
            metrics=metrics,
        )
    if status != RunTerminalStatus.COMPLETED.value:
        raise LA1ArtifactIntegrityError("unsupported LA1 terminal status")
    _verify_artifacts(directory, metrics)
    scenario = config["scenario"]
    if scenario == "success":
        inputs = _success_inputs(config["run_id"])
        replayed = replay_gate_episode(events=events, **inputs)
    elif scenario == "failure_recovery":
        inputs = _failure_inputs(config["run_id"])
        replayed = replay_failure_reorganization(
            candidates=inputs["candidates"],
            admission_policy=inputs["admission_policy"],
            multi_policy=inputs["multi_policy"],
            run_budget=inputs["run_budget"],
            events=events,
        )
        checkpoint = FailureReorganizationCheckpoint.from_dict(
            _read_json(directory / "artifacts" / "failure_checkpoint.json")
        )
        resumed = resume_failure_reorganization(
            checkpoint=checkpoint,
            candidates=inputs["candidates"],
            admission_policy=inputs["admission_policy"],
            multi_policy=inputs["multi_policy"],
            run_budget=inputs["run_budget"],
            suffix_events=events[checkpoint.next_public_state_revision :],
        )
        if resumed != replayed:
            raise LA1ArtifactIntegrityError(
                "persisted checkpoint resume differs from full replay"
            )
    elif scenario == "governance_paths":
        replayed = run_governance_evidence(config["run_id"])
        if replayed.events != events:
            raise LA1ArtifactIntegrityError("persisted governance paths do not replay")
        if _read_json(directory / "artifacts" / "governance_paths.json") != dict(
            replayed.artifact
        ):
            raise LA1ArtifactIntegrityError(
                "persisted governance evidence differs from replay"
            )
    else:
        raise LA1ArtifactIntegrityError("persisted scenario is invalid")
    organization = OrganizationSnapshot.from_dict(
        _read_json(directory / "artifacts" / "organization_snapshot.json")
    )
    if organization != replayed.organization_snapshot:
        raise LA1ArtifactIntegrityError(
            "persisted organization snapshot does not replay"
        )
    rebuilt = summarize_la1_run(
        scenario=scenario,
        events=events,
        organization_snapshot=organization,
        ledger_totals=replayed.ledger_totals,
        terminal_projection_sha256=replayed.terminal_projection_sha256,
        run_budget=config["run_budget"],
        wall_time_ms=metrics["cost_vector"]["wall_time_ms"],
        cpu_time_ms=metrics["cost_vector"]["cpu_time_ms"],
        deterministic_check_calls=metrics["cost_vector"]["deterministic_check_calls"],
    )
    if scenario == "governance_paths":
        _augment_governance_metrics(
            rebuilt,
            wrapper_events=events,
            native_artifact=replayed.artifact,
        )
    rebuilt["artifact_sha256"] = dict(metrics["artifact_sha256"])
    if rebuilt != metrics:
        raise LA1ArtifactIntegrityError("persisted LA1 metrics do not replay")
    if (directory / "summary.md").read_text(encoding="utf-8") != _summary_markdown(
        metrics
    ):
        raise LA1ArtifactIntegrityError("completed run summary does not replay")
    final_state = {
        "scenario": scenario,
        "status": "completed",
        "terminal_projection_sha256": replayed.terminal_projection_sha256,
        "organization_snapshot_sha256": organization.snapshot_hash,
        "ledger_totals": _json_ready(replayed.ledger_totals),
        "artifact_sha256": metrics["artifact_sha256"],
    }
    if _sha256(final_state) != finalization.get("final_state_sha256"):
        raise LA1ArtifactIntegrityError("completed final state hash mismatch")
    return LA1RunExecution(
        run_directory=directory,
        scenario=scenario,
        status="completed",
        events=events,
        organization_snapshot=organization,
        ledger_totals=replayed.ledger_totals,
        terminal_projection_sha256=replayed.terminal_projection_sha256,
        metrics=metrics,
    )


class _LA1ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LA1CLIUsageError(message)


def _parse_args(
    argv: list[str] | tuple[str, ...] | None,
) -> argparse.Namespace:
    parser = _LA1ArgumentParser(
        prog="python -m biofield.la1_artifacts",
        description="Prepare, execute, replay, or summarize sealed LA1 runs.",
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_LA1ArgumentParser,
    )

    prepare = commands.add_parser("prepare")
    prepare.add_argument(
        "--output",
        "--output-directory",
        dest="output",
        required=True,
    )
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS),
    )

    for command in ("run", "replay", "summarize"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--run-directory", required=True)
    return parser.parse_args(argv)


def _emit_json(value: Mapping[str, Any], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(
        json.dumps(
            _json_ready(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _execution_summary(execution: LA1RunExecution) -> dict[str, Any]:
    return {
        "run_directory": str(execution.run_directory),
        "scenario": execution.scenario,
        "status": execution.status,
        "event_count": len(execution.events),
        "terminal_projection_sha256": (execution.terminal_projection_sha256),
    }


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    """Minimal offline CLI over the sealed LA1 artifact APIs."""

    try:
        arguments = _parse_args(argv)
        if arguments.command == "prepare":
            directory = prepare_la1_run(
                output_directory=arguments.output,
                run_id=arguments.run_id,
                scenario=arguments.scenario,
            )
            _emit_json(
                {
                    "run_directory": str(directory),
                    "run_id": arguments.run_id,
                    "scenario": arguments.scenario,
                    "status": "prepared",
                }
            )
            return 0
        if arguments.command == "run":
            _emit_json(_execution_summary(execute_la1_run(arguments.run_directory)))
            return 0
        if arguments.command == "replay":
            _emit_json(_execution_summary(replay_la1_run(arguments.run_directory)))
            return 0
        if arguments.command == "summarize":
            replayed = replay_la1_run(arguments.run_directory)
            _emit_json(dict(replayed.metrics))
            return 0
        raise LA1ArtifactError(f"unknown command: {arguments.command}")
    except (ArtifactError, LA1ArtifactError, OSError, ValueError) as error:
        _emit_json(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            },
            error=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
