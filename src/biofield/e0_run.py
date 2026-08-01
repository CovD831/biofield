from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .e0 import (
    F0PublicEventAdapter,
    PublicEvent,
    PublicEventReplayError,
    PublicEventReplayer,
    PublicReplayCheckpoint,
)
from .evidence_task import load_task_bundle
from .f0 import DeterministicF0Executor, F0Experiment, F0RunConfig
from .resources import fixture_root


E0_ARTIFACT_RUNNER_VERSION = "e0.artifact-runner.v2"
E0_EXPERIMENT_ID = "e0"
E0_CLAIM_LIMIT = "E0 deterministic public replay only"
_LOCK_SCHEMA_VERSION = 2
_LEGACY_LOCK_SCHEMA_VERSION = 1
_LEGACY_ARTIFACT_RUNNER_VERSION = "e0.artifact-runner.v1"
_TERMINAL_CASES = (
    "completed",
    "failed",
    "budget_exhausted",
    "max_cycles",
)
_SOURCE_FILES = (
    "__init__.py",
    "artifacts.py",
    "contracts.py",
    "e0.py",
    "e0_run.py",
    "evidence_task.py",
    "f0.py",
    "ledger.py",
    "residual.py",
    "resources.py",
)
_FIXTURE_FILES = (
    "r1/cold_chain_readiness/answer_key.v1.json",
    "r1/cold_chain_readiness/task.v1.json",
)
_LEGACY_V1_SOURCE_HASHES = {
    "__init__.py": ("48b56c1c757983ce5eb397d74ddac6e1e38730f1c045440ed618ee6968e3bcb2"),
    "artifacts.py": (
        "eb39d05b4e57cd30e6261cee370b5be71a051dff5352a9eb37653a4f0c2dee92"
    ),
    "contracts.py": (
        "8a14c84c8c3d51a8662a34ae2f250a5730c9a422c623fc47b740146b3ef630d5"
    ),
    "e0.py": "256d1c08cc27cbfe52ea17155391069bdd11b9f8dd1309c29ad936e53f6b9ba1",
    "e0_run.py": ("fa53744145b6088f85a8efe304f1c1e7fc0afa77f858aabceefe7a261cb868b0"),
    "evidence_task.py": (
        "6767de90ebb4275555b9593af5f0a33832353dff52daedc739a7d408f8e3eb13"
    ),
    "f0.py": "d2a9801e64f9867fd0f0e83471f305eded96ca6cf1590f7beabdc2b0c1e2100d",
    "ledger.py": ("ac2d4d3447e0059fdc5f7d809083095a863e2442db8a8032f4ff4164c322bd6e"),
    "residual.py": ("de0a7907c8f479942364d4372942c077f869182f8397efcac01dccec93a007fc"),
    "resources.py": (
        "89399e314ef5d446853853c680f6331efeece4c257512c138625b05c7b5f8213"
    ),
}
_COMPLETED_RUN_FILES = {
    "checkpoints.json",
    "config.json",
    "environment.json",
    "events.ndjson",
    "metrics.json",
    "preregistration.lock.json",
    "replay.json",
    "source_manifest.json",
    "summary.json",
    "terminal.json",
}
_FAILED_RUN_FILES = {
    "config.json",
    "environment.json",
    "events.ndjson",
    "failure.json",
    "metrics.json",
    "preregistration.lock.json",
    "source_manifest.json",
    "summary.json",
    "terminal.json",
}


class E0ArtifactError(RuntimeError):
    """Base error for the persistent E0 runner."""


class E0ArtifactExistsError(E0ArtifactError, FileExistsError):
    """Raised instead of overwriting a lock or run."""


class E0RunFinalizedError(E0ArtifactError):
    """Raised when a finalized run is mutated."""


class E0RunIntegrityError(E0ArtifactError):
    """Raised when a lock, source run, run artifact, or replay is invalid."""


class E0RunExecutionError(E0ArtifactError):
    """Raised after an execution failure has been sealed."""

    def __init__(self, message: str, *, run_directory: Path) -> None:
        super().__init__(message)
        self.run_directory = run_directory


@dataclass(frozen=True)
class E0ReplayReport:
    verified: bool
    terminal_case_count: int
    checkpoint_equivalent_count: int
    terminal_statuses: tuple[str, ...]
    replay_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "terminal_case_count": self.terminal_case_count,
            "checkpoint_equivalent_count": self.checkpoint_equivalent_count,
            "terminal_statuses": list(self.terminal_statuses),
            "replay_sha256": self.replay_sha256,
        }


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
        raise E0RunIntegrityError("artifact value must be finite JSON") from error


def _json_file_bytes(value: Any) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return _sha256(path.read_bytes())
    except OSError as error:
        raise E0RunIntegrityError(f"cannot hash artifact: {path.name}") from error


def _safe_segment(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise E0RunIntegrityError(f"{label} must be one safe path segment")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_create_bytes(path: Path, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise E0RunIntegrityError("artifact content must be bytes")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise E0ArtifactExistsError(
                f"artifact already exists: {path.name}"
            ) from error
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise E0RunIntegrityError(f"cannot read {path.name} as JSON") from error
    if not isinstance(value, dict):
        raise E0RunIntegrityError(f"{path.name} must contain a JSON object")
    return value


def _source_hashes() -> dict[str, str]:
    package_root = Path(__file__).resolve().parent
    return {
        filename: _file_sha256(package_root / filename) for filename in _SOURCE_FILES
    }


def _fixture_hashes() -> dict[str, str]:
    root = fixture_root()
    return {
        relative_path: _file_sha256(root / relative_path)
        for relative_path in _FIXTURE_FILES
    }


def _validated_lock_runner_version(lock: Mapping[str, Any]) -> str:
    if (
        lock.get("experiment_id") != E0_EXPERIMENT_ID
        or lock.get("stream_kind") != "f0.native.v2"
        or lock.get("claim_limit") != E0_CLAIM_LIMIT
        or lock.get("terminal_cases") != list(_TERMINAL_CASES)
    ):
        raise E0RunIntegrityError("E0 lock contract mismatch")
    contract_version = (
        lock.get("schema_version"),
        lock.get("runner_version"),
    )
    if contract_version == (
        _LOCK_SCHEMA_VERSION,
        E0_ARTIFACT_RUNNER_VERSION,
    ):
        if lock.get("source_hashes") != _source_hashes():
            raise E0RunIntegrityError("E0 lock source hash mismatch")
        if lock.get("fixture_hashes") != _fixture_hashes():
            raise E0RunIntegrityError("E0 lock fixture hash mismatch")
        return E0_ARTIFACT_RUNNER_VERSION
    if contract_version == (
        _LEGACY_LOCK_SCHEMA_VERSION,
        _LEGACY_ARTIFACT_RUNNER_VERSION,
    ):
        if (
            lock.get("source_hashes") != _LEGACY_V1_SOURCE_HASHES
            or "fixture_hashes" in lock
        ):
            raise E0RunIntegrityError("E0 legacy lock source contract mismatch")
        return _LEGACY_ARTIFACT_RUNNER_VERSION
    raise E0RunIntegrityError("unsupported E0 lock schema/runner pair")


@lru_cache(maxsize=1)
def _git_snapshot() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--short"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {
            "available": False,
            "commit": None,
            "dirty": None,
            "dirty_state_sha256": None,
        }
    return {
        "available": True,
        "commit": head,
        "dirty": bool(dirty),
        "dirty_state_sha256": _sha256(dirty.encode("utf-8")),
    }


def _environment() -> dict[str, Any]:
    dependencies: dict[str, str] = {}
    for package in ("jsonschema", "numpy"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "unavailable"
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "dependencies": dependencies,
        "git": _git_snapshot(),
    }


def _event_bundle_sha256(events: tuple[PublicEvent, ...]) -> str:
    return _sha256(_canonical_json_bytes([event.to_dict() for event in events]))


def _source_descriptor(
    expected_status: str,
    run_directory: str | os.PathLike[str],
) -> dict[str, Any]:
    requested = Path(run_directory).expanduser()
    if requested.is_symlink():
        raise E0RunIntegrityError(
            f"source run {expected_status!r} cannot be a symbolic link"
        )
    root = requested.resolve()
    try:
        events = F0PublicEventAdapter.from_run_directory(root)
        replayed = PublicEventReplayer.replay(events)
    except (OSError, ValueError, PublicEventReplayError) as error:
        raise E0RunIntegrityError(
            f"source run {expected_status!r} is not valid native.v2 evidence"
        ) from error
    if (
        replayed.terminal_status != expected_status
        or not replayed.primitive_replay_verified
        or not replayed.evidence_feedback_verified
        or replayed.public_terminal_projection_sha256 is None
    ):
        raise E0RunIntegrityError(
            f"source run {expected_status!r} does not prove its terminal path"
        )
    started = events[0]
    if (
        started.event_type != "run_started"
        or started.payload.get("stream_kind") != "f0.native.v2"
    ):
        raise E0RunIntegrityError("E0 source run must use f0.native.v2")
    return {
        "terminal_case": expected_status,
        "run_directory": str(root),
        "source_finalization_sha256": _file_sha256(root / "finalization.json"),
        "public_event_count": len(events),
        "public_event_bundle_sha256": _event_bundle_sha256(events),
        "source_final_state_sha256": replayed.source_final_state_sha256,
        "public_terminal_projection_sha256": (
            replayed.public_terminal_projection_sha256
        ),
    }


def _lock_content(
    *,
    lock_id: str,
    source_run_directories: Mapping[str, str | os.PathLike[str]],
) -> dict[str, Any]:
    if tuple(sorted(source_run_directories)) != tuple(sorted(_TERMINAL_CASES)):
        raise E0RunIntegrityError(
            "E0 prepare requires completed, failed, budget_exhausted, "
            "and max_cycles source runs"
        )
    return {
        "schema_version": _LOCK_SCHEMA_VERSION,
        "lock_id": lock_id,
        "experiment_id": E0_EXPERIMENT_ID,
        "runner_version": E0_ARTIFACT_RUNNER_VERSION,
        "stream_kind": "f0.native.v2",
        "claim_limit": E0_CLAIM_LIMIT,
        "terminal_cases": list(_TERMINAL_CASES),
        "checkpoint_strategy": "deterministic_midstream_prefix",
        "source_hashes": _source_hashes(),
        "fixture_hashes": _fixture_hashes(),
        "source_runs": {
            status: _source_descriptor(
                status,
                source_run_directories[status],
            )
            for status in _TERMINAL_CASES
        },
    }


def prepare_e0_run(
    *,
    lock_directory: str | os.PathLike[str],
    lock_id: str,
    source_run_directories: Mapping[str, str | os.PathLike[str]],
) -> Path:
    safe_lock_id = _safe_segment(lock_id, "lock_id")
    root = Path(lock_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / safe_lock_id
    try:
        directory.mkdir()
    except FileExistsError as error:
        raise E0ArtifactExistsError(
            f"E0 lock already exists: {safe_lock_id}"
        ) from error
    lock = _lock_content(
        lock_id=safe_lock_id,
        source_run_directories=source_run_directories,
    )
    lock_path = directory / "e0.lock.json"
    _atomic_create_bytes(lock_path, _json_file_bytes(lock))
    _atomic_create_bytes(
        directory / "lock.seal.json",
        _json_file_bytes(
            {
                "schema_version": 1,
                "lock_id": safe_lock_id,
                "e0_lock_sha256": _file_sha256(lock_path),
            }
        ),
    )
    return lock_path


def _verified_lock(lock_path: Path) -> dict[str, Any]:
    seal_path = lock_path.with_name("lock.seal.json")
    if lock_path.is_symlink() or seal_path.is_symlink():
        raise E0RunIntegrityError("E0 lock or lock seal cannot be a symbolic link")
    if not lock_path.is_file() or not seal_path.is_file():
        raise E0RunIntegrityError("E0 lock or lock seal is missing")
    seal = _read_json(seal_path)
    if seal.get("e0_lock_sha256") != _file_sha256(lock_path):
        raise E0RunIntegrityError("E0 lock hash mismatch")
    lock = _read_json(lock_path)
    if _validated_lock_runner_version(lock) != E0_ARTIFACT_RUNNER_VERSION:
        raise E0RunIntegrityError("E0 schema1/runner v1 locks are replay-only")
    return lock


class E0RunStore:
    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory

    @classmethod
    def create(
        cls,
        output_directory: str | os.PathLike[str],
        run_id: str,
    ) -> E0RunStore:
        safe_run_id = _safe_segment(run_id, "run_id")
        root = Path(output_directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        experiment = root / E0_EXPERIMENT_ID
        experiment.mkdir(exist_ok=True)
        run_directory = experiment / safe_run_id
        try:
            run_directory.mkdir()
        except FileExistsError as error:
            raise E0ArtifactExistsError(
                f"E0 run already exists: {safe_run_id}"
            ) from error
        return cls(run_directory)

    @classmethod
    def open(cls, run_directory: str | os.PathLike[str]) -> E0RunStore:
        requested = Path(run_directory).expanduser()
        if requested.is_symlink():
            raise E0RunIntegrityError("E0 run directory cannot be a symbolic link")
        root = requested.resolve()
        if not root.is_dir() or root.is_symlink():
            raise E0RunIntegrityError("E0 run directory is invalid")
        return cls(root)

    def has(self, filename: str) -> bool:
        return (self.run_directory / _safe_segment(filename, "filename")).is_file()

    def write_json(self, filename: str, value: Any) -> Path:
        self._ensure_mutable()
        path = self.run_directory / _safe_segment(filename, "filename")
        _atomic_create_bytes(path, _json_file_bytes(value))
        return path

    def write_bytes(self, filename: str, content: bytes) -> Path:
        self._ensure_mutable()
        path = self.run_directory / _safe_segment(filename, "filename")
        _atomic_create_bytes(path, content)
        return path

    def finalize(
        self,
        *,
        status: str,
        reason: str,
        metadata: Mapping[str, Any],
    ) -> None:
        self._ensure_mutable()
        terminal = {
            "schema_version": 1,
            "experiment_id": E0_EXPERIMENT_ID,
            "run_id": self.run_directory.name,
            "status": status,
            "reason": reason,
            "metadata": dict(metadata),
        }
        _atomic_create_bytes(
            self.run_directory / "terminal.json",
            _json_file_bytes(terminal),
        )
        file_hashes = {
            path.name: _file_sha256(path)
            for path in sorted(self.run_directory.iterdir())
            if path.is_file() and path.name != "seal.json"
        }
        seal = {
            "schema_version": 1,
            "experiment_id": E0_EXPERIMENT_ID,
            "run_id": self.run_directory.name,
            "runner_version": E0_ARTIFACT_RUNNER_VERSION,
            "claim_limit": E0_CLAIM_LIMIT,
            "status": status,
            "file_sha256": file_hashes,
            "artifact_bundle_sha256": _sha256(_canonical_json_bytes(file_hashes)),
        }
        _atomic_create_bytes(
            self.run_directory / "seal.json",
            _json_file_bytes(seal),
        )

    def _ensure_mutable(self) -> None:
        if (self.run_directory / "terminal.json").exists() or (
            self.run_directory / "seal.json"
        ).exists():
            raise E0RunFinalizedError("E0 run is finalized and cannot be mutated")


def _verify_locked_sources(lock: Mapping[str, Any]) -> dict[str, Any]:
    source_runs = lock.get("source_runs")
    if not isinstance(source_runs, Mapping):
        raise E0RunIntegrityError("E0 lock source manifest is malformed")
    actual = {
        status: _source_descriptor(
            status,
            source_runs[status]["run_directory"],
        )
        for status in _TERMINAL_CASES
    }
    if actual != dict(source_runs):
        raise E0RunIntegrityError("E0 source runs differ from lock")
    return actual


def _checkpoint_cut(events: tuple[PublicEvent, ...]) -> int:
    if len(events) < 3:
        raise E0RunIntegrityError("E0 source stream is too short for checkpoint")
    return max(1, min(len(events) - 1, len(events) // 2))


def _replay_projection(result: Any) -> dict[str, Any]:
    return {
        "applied_event_count": result.applied_event_count,
        "applied_event_ids": list(result.applied_event_ids),
        "terminal": result.terminal,
        "terminal_status": result.terminal_status,
        "source_final_state_sha256": result.source_final_state_sha256,
        "public_terminal_projection_sha256": (result.public_terminal_projection_sha256),
        "primitive_replay_verified": result.primitive_replay_verified,
        "evidence_feedback_verified": result.evidence_feedback_verified,
        "final_state_sha256": result.final_state_sha256,
    }


def _execute_cases(
    source_runs: Mapping[str, Any],
) -> tuple[
    bytes,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    event_lines: list[bytes] = []
    checkpoints: dict[str, Any] = {}
    replay_cases: dict[str, Any] = {}
    terminal_cases: dict[str, str] = {}
    for status in _TERMINAL_CASES:
        events = F0PublicEventAdapter.from_run_directory(
            source_runs[status]["run_directory"]
        )
        full = PublicEventReplayer.replay(events)
        cut = _checkpoint_cut(events)
        checkpoint = PublicEventReplayer.create_checkpoint(events[:cut])
        resumed = PublicEventReplayer.replay_from_checkpoint(
            checkpoint,
            events[cut:],
        )
        if full != resumed:
            raise E0RunIntegrityError(
                f"checkpoint replay differs for terminal case {status}"
            )
        if full.terminal_status != status:
            raise E0RunIntegrityError(
                f"terminal case {status} replayed as {full.terminal_status}"
            )
        for event in events:
            event_lines.append(
                _json_file_bytes(
                    {
                        "terminal_case": status,
                        "public_event": event.to_dict(),
                    }
                )
            )
        checkpoints[status] = checkpoint.to_dict()
        replay_cases[status] = {
            "checkpoint_cut": cut,
            "event_bundle_sha256": _event_bundle_sha256(events),
            "full": _replay_projection(full),
            "resumed": _replay_projection(resumed),
            "checkpoint_equivalent": True,
        }
        terminal_cases[status] = str(full.terminal_status)
    replay = {
        "schema_version": 1,
        "runner_version": E0_ARTIFACT_RUNNER_VERSION,
        "cases": replay_cases,
    }
    metrics = {
        "terminal_case_count": len(_TERMINAL_CASES),
        "terminal_cases": terminal_cases,
        "public_event_count": len(event_lines),
        "primitive_replay_verified": sum(
            case["full"]["primitive_replay_verified"] for case in replay_cases.values()
        ),
        "evidence_feedback_verified": sum(
            case["full"]["evidence_feedback_verified"] for case in replay_cases.values()
        ),
        "checkpoint_equivalent": sum(
            case["checkpoint_equivalent"] for case in replay_cases.values()
        ),
    }
    summary = {
        "title": "E0 native.v2 deterministic public replay",
        "claim_limit": E0_CLAIM_LIMIT,
        "terminal_case_count": len(_TERMINAL_CASES),
        "terminal_cases": terminal_cases,
        "sealed": True,
        "checkpoint_full_replay_equivalent": True,
    }
    return (
        b"".join(event_lines),
        checkpoints,
        replay,
        {
            "metrics": metrics,
            "summary": summary,
        },
    )


def _write_failure_artifacts(
    store: E0RunStore,
    error: Exception,
    *,
    started_wall: int,
    started_cpu: int,
) -> None:
    elapsed_wall_ms = max(
        1,
        (time.perf_counter_ns() - started_wall) // 1_000_000,
    )
    elapsed_cpu_ms = max(
        1,
        (time.process_time_ns() - started_cpu) // 1_000_000,
    )
    zero_cost_fields = [
        "model_calls",
        "input_tokens",
        "output_tokens",
        "tool_calls",
        "bytes_transferred",
        "communication_messages",
        "communication_tokens",
        "state_update_calls",
        "verifier_calls",
        "deterministic_check_calls",
        "judge_calls",
        "human_escalations",
        "retry_count",
    ]
    defaults: tuple[tuple[str, Any], ...] = (
        ("events.ndjson", b""),
        (
            "metrics.json",
            {
                "terminal_case_count": 0,
                "terminal_cases": {},
                "failure_retained": True,
                "cost_vector": {
                    "model_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "tool_calls": 0,
                    "wall_time_ms": elapsed_wall_ms,
                    "cpu_time_ms": elapsed_cpu_ms,
                    "bytes_transferred": 0,
                    "communication_messages": 0,
                    "communication_tokens": 0,
                    "state_update_calls": 0,
                    "verifier_calls": 0,
                    "deterministic_check_calls": 0,
                    "judge_calls": 0,
                    "human_escalations": 0,
                    "retry_count": 0,
                },
                "cost_vector_accounting": {
                    "basis": "partial_run_until_failure",
                    "elapsed_fields": ["wall_time_ms", "cpu_time_ms"],
                    "zero_fields": zero_cost_fields,
                },
            },
        ),
        (
            "summary.json",
            {
                "title": "E0 native.v2 deterministic public replay",
                "claim_limit": E0_CLAIM_LIMIT,
                "sealed": True,
                "status": "failed",
            },
        ),
    )
    for filename, value in defaults:
        if store.has(filename):
            continue
        if isinstance(value, bytes):
            store.write_bytes(filename, value)
        else:
            store.write_json(filename, value)
    if not store.has("failure.json"):
        store.write_json(
            "failure.json",
            {
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )
    store.finalize(
        status="failed",
        reason="E0 execution failed closed",
        metadata={"error_type": type(error).__name__},
    )


def execute_e0_run(
    *,
    lock_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
    run_id: str,
) -> Path:
    requested_lock_path = Path(lock_path).expanduser()
    if requested_lock_path.is_symlink():
        raise E0RunIntegrityError("E0 lock cannot be a symbolic link")
    source_lock_path = requested_lock_path.resolve()
    lock = _verified_lock(source_lock_path)
    store = E0RunStore.create(output_directory, run_id)
    started_wall = time.perf_counter_ns()
    started_cpu = time.process_time_ns()
    lock_bytes = source_lock_path.read_bytes()
    store.write_bytes("preregistration.lock.json", lock_bytes)
    store.write_json(
        "config.json",
        {
            "schema_version": 1,
            "experiment_id": E0_EXPERIMENT_ID,
            "run_id": store.run_directory.name,
            "runner_version": E0_ARTIFACT_RUNNER_VERSION,
            "stream_kind": "f0.native.v2",
            "claim_limit": E0_CLAIM_LIMIT,
            "lock_sha256": _sha256(lock_bytes),
            "terminal_cases": list(_TERMINAL_CASES),
            "checkpoint_strategy": lock["checkpoint_strategy"],
        },
    )
    store.write_json("environment.json", _environment())
    store.write_json(
        "source_manifest.json",
        {
            "source_hashes": lock["source_hashes"],
            "fixture_hashes": lock["fixture_hashes"],
            "source_runs": lock["source_runs"],
        },
    )
    try:
        source_runs = _verify_locked_sources(lock)
        events, checkpoints, replay, output = _execute_cases(source_runs)
        elapsed_wall_ms = max(
            1,
            (time.perf_counter_ns() - started_wall) // 1_000_000,
        )
        elapsed_cpu_ms = max(
            1,
            (time.process_time_ns() - started_cpu) // 1_000_000,
        )
        metrics = dict(output["metrics"])
        metrics["cost_vector"] = {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": 0,
            "wall_time_ms": elapsed_wall_ms,
            "cpu_time_ms": elapsed_cpu_ms,
            "bytes_transferred": len(events),
            "communication_messages": 0,
            "communication_tokens": 0,
            "state_update_calls": 0,
            "verifier_calls": len(_TERMINAL_CASES) * 2,
            "deterministic_check_calls": len(_TERMINAL_CASES) * 2,
            "judge_calls": 0,
            "human_escalations": 0,
            "retry_count": 0,
        }
        store.write_bytes("events.ndjson", events)
        store.write_json("checkpoints.json", checkpoints)
        store.write_json("replay.json", replay)
        store.write_json("metrics.json", metrics)
        store.write_json("summary.json", output["summary"])
        store.finalize(
            status="completed",
            reason="four native.v2 terminal paths replayed and checkpointed",
            metadata={
                "terminal_case_count": len(_TERMINAL_CASES),
                "public_event_count": metrics["public_event_count"],
            },
        )
    except Exception as error:
        try:
            _write_failure_artifacts(
                store,
                error,
                started_wall=started_wall,
                started_cpu=started_cpu,
            )
        except Exception as sealing_error:
            raise E0RunExecutionError(
                f"{error}; additionally failed to seal failure: {sealing_error}",
                run_directory=store.run_directory,
            ) from error
        raise E0RunExecutionError(
            str(error),
            run_directory=store.run_directory,
        ) from error
    return store.run_directory


def _verify_run_seal(run_directory: Path) -> dict[str, Any]:
    seal_path = run_directory / "seal.json"
    if seal_path.is_symlink():
        raise E0RunIntegrityError("E0 seal cannot be a symbolic link")
    if not seal_path.is_file():
        raise E0RunIntegrityError("E0 run is not finalized")
    seal = _read_json(seal_path)
    file_hashes = seal.get("file_sha256")
    if not isinstance(file_hashes, Mapping):
        raise E0RunIntegrityError("E0 run seal file hashes are malformed")
    current_files = {
        path.name
        for path in run_directory.iterdir()
        if path.is_file() and path.name != "seal.json"
    }
    if set(file_hashes) != current_files:
        raise E0RunIntegrityError("E0 sealed run file set mismatch")
    status = seal.get("status")
    file_contract_valid = (
        current_files == _COMPLETED_RUN_FILES
        if status == "completed"
        else (
            _FAILED_RUN_FILES <= current_files
            and current_files <= (_COMPLETED_RUN_FILES | {"failure.json"})
        )
        if status == "failed"
        else False
    )
    if not file_contract_valid:
        raise E0RunIntegrityError("E0 sealed run required file set mismatch")
    for filename, digest in file_hashes.items():
        path = run_directory / _safe_segment(str(filename), "sealed filename")
        if path.is_symlink() or _file_sha256(path) != digest:
            raise E0RunIntegrityError(f"E0 sealed run hash mismatch: {filename}")
    lock = _read_json(run_directory / "preregistration.lock.json")
    lock_runner_version = _validated_lock_runner_version(lock)
    if (
        seal.get("artifact_bundle_sha256")
        != _sha256(_canonical_json_bytes(dict(file_hashes)))
        or seal.get("experiment_id") != E0_EXPERIMENT_ID
        or seal.get("runner_version") != lock_runner_version
        or seal.get("claim_limit") != E0_CLAIM_LIMIT
    ):
        raise E0RunIntegrityError("E0 run seal contract mismatch")
    terminal = _read_json(run_directory / "terminal.json")
    if (
        terminal.get("experiment_id") != E0_EXPERIMENT_ID
        or terminal.get("run_id") != run_directory.name
        or terminal.get("status") != seal.get("status")
    ):
        raise E0RunIntegrityError("E0 terminal and seal disagree")
    return seal


def _read_persisted_events(
    path: Path,
) -> dict[str, tuple[PublicEvent, ...]]:
    grouped: dict[str, list[PublicEvent]] = {status: [] for status in _TERMINAL_CASES}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise E0RunIntegrityError("cannot read E0 events") from error
    for line in lines:
        try:
            value = json.loads(line)
            status = value["terminal_case"]
            event = PublicEvent.from_dict(value["public_event"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise E0RunIntegrityError("persisted E0 event is invalid") from error
        if status not in grouped:
            raise E0RunIntegrityError("persisted E0 terminal case is invalid")
        grouped[status].append(event)
    return {status: tuple(grouped[status]) for status in _TERMINAL_CASES}


def replay_e0_run(
    run_directory: str | os.PathLike[str],
) -> E0ReplayReport:
    store = E0RunStore.open(run_directory)
    seal = _verify_run_seal(store.run_directory)
    if seal.get("status") != "completed":
        raise E0RunIntegrityError("only completed E0 runs can replay")
    config = _read_json(store.run_directory / "config.json")
    lock_path = store.run_directory / "preregistration.lock.json"
    if config.get("lock_sha256") != _file_sha256(lock_path):
        raise E0RunIntegrityError("persisted E0 lock hash mismatch")
    lock = _read_json(lock_path)
    runner_version = _validated_lock_runner_version(lock)
    if (
        config.get("runner_version") != runner_version
        or config.get("stream_kind") != "f0.native.v2"
        or config.get("claim_limit") != E0_CLAIM_LIMIT
        or config.get("terminal_cases") != list(_TERMINAL_CASES)
    ):
        raise E0RunIntegrityError("persisted E0 config contract mismatch")
    source_manifest = _read_json(store.run_directory / "source_manifest.json")
    source_manifest_mismatch = source_manifest.get("source_hashes") != lock.get(
        "source_hashes"
    ) or source_manifest.get("source_runs") != lock.get("source_runs")
    if runner_version == E0_ARTIFACT_RUNNER_VERSION:
        source_manifest_mismatch = source_manifest_mismatch or (
            source_manifest.get("fixture_hashes") != lock.get("fixture_hashes")
        )
    elif "fixture_hashes" in source_manifest:
        source_manifest_mismatch = True
    if source_manifest_mismatch:
        raise E0RunIntegrityError("persisted E0 source manifest mismatch")
    grouped = _read_persisted_events(store.run_directory / "events.ndjson")
    checkpoints = _read_json(store.run_directory / "checkpoints.json")
    persisted_replay = _read_json(store.run_directory / "replay.json")
    replay_cases: dict[str, Any] = {}
    terminal_statuses: list[str] = []
    for status in _TERMINAL_CASES:
        events = grouped[status]
        if (
            not events
            or _event_bundle_sha256(events)
            != lock["source_runs"][status]["public_event_bundle_sha256"]
        ):
            raise E0RunIntegrityError(f"persisted E0 event bundle differs for {status}")
        try:
            checkpoint = PublicReplayCheckpoint.from_dict(checkpoints[status])
            full = PublicEventReplayer.replay(events)
            resumed = PublicEventReplayer.replay_from_checkpoint(
                checkpoint,
                events[checkpoint.next_sequence :],
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            PublicEventReplayError,
        ) as error:
            raise E0RunIntegrityError(
                f"persisted E0 replay failed for {status}"
            ) from error
        if full != resumed or full.terminal_status != status:
            raise E0RunIntegrityError(f"persisted E0 checkpoint differs for {status}")
        replay_cases[status] = {
            "checkpoint_cut": checkpoint.next_sequence,
            "event_bundle_sha256": _event_bundle_sha256(events),
            "full": _replay_projection(full),
            "resumed": _replay_projection(resumed),
            "checkpoint_equivalent": True,
        }
        terminal_statuses.append(str(full.terminal_status))
    computed_replay = {
        "schema_version": 1,
        "runner_version": runner_version,
        "cases": replay_cases,
    }
    if computed_replay != persisted_replay:
        raise E0RunIntegrityError("persisted E0 replay report mismatch")
    replay_sha256 = _sha256(_canonical_json_bytes(computed_replay))
    return E0ReplayReport(
        verified=True,
        terminal_case_count=len(_TERMINAL_CASES),
        checkpoint_equivalent_count=len(_TERMINAL_CASES),
        terminal_statuses=tuple(terminal_statuses),
        replay_sha256=replay_sha256,
    )


def summarize_e0_run(
    run_directory: str | os.PathLike[str],
) -> dict[str, Any]:
    replay_e0_run(run_directory)
    summary = _read_json(Path(run_directory).expanduser().resolve() / "summary.json")
    if (
        summary.get("claim_limit") != E0_CLAIM_LIMIT
        or summary.get("terminal_case_count") != len(_TERMINAL_CASES)
        or summary.get("sealed") is not True
    ):
        raise E0RunIntegrityError("E0 summary contract mismatch")
    return summary


def generate_e0_source_runs(
    *,
    output_directory: str | os.PathLike[str],
    source_set_id: str,
) -> dict[str, Path]:
    safe_source_set_id = _safe_segment(source_set_id, "source_set_id")
    bundle = load_task_bundle("cold_chain_readiness")
    settings = {
        "completed": (3, 5, None, None),
        "failed": (3, 5, "contradiction_resolution", None),
        "budget_exhausted": (1, 5, None, None),
        "max_cycles": (2, 2, None, "fact_extraction"),
    }
    generated: dict[str, Path] = {}
    for expected_status in _TERMINAL_CASES:
        action_budget, max_cycles, fail_on, invalid_on = settings[expected_status]
        result = F0Experiment(
            bundle=bundle,
            executor=DeterministicF0Executor(
                bundle,
                fail_on_requirement=fail_on,
                invalid_on_requirement=invalid_on,
            ),
            config=F0RunConfig(
                output_directory=Path(output_directory),
                run_id=f"{safe_source_set_id}-{expected_status}",
                action_budget=action_budget,
                max_cycles=max_cycles,
            ),
        ).run()
        if result.status.value != expected_status:
            raise E0RunIntegrityError(
                f"generated source {expected_status} ended as {result.status.value}"
            )
        generated[expected_status] = result.run_directory.resolve()
    return generated


class _CLIArgumentError(ValueError):
    pass


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _CLIArgumentError(message)


def _argument_parser() -> argparse.ArgumentParser:
    parser = _JSONArgumentParser(
        prog="python -m biofield.e0_run",
        description="Prepare, execute, replay, and summarize sealed E0 runs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    sources = commands.add_parser(
        "sources",
        help="generate the frozen four-terminal native.v2 F0 source matrix",
    )
    sources.add_argument("--output-directory", required=True, type=Path)
    sources.add_argument("--source-set-id", required=True)

    prepare = commands.add_parser(
        "prepare",
        help="freeze four explicit native.v2 source-run paths",
    )
    prepare.add_argument("--lock-directory", required=True, type=Path)
    prepare.add_argument("--lock-id", required=True)
    prepare.add_argument("--completed", required=True, type=Path)
    prepare.add_argument("--failed", required=True, type=Path)
    prepare.add_argument("--budget-exhausted", required=True, type=Path)
    prepare.add_argument("--max-cycles", required=True, type=Path)

    run = commands.add_parser("run", help="execute one prepared E0 matrix")
    run.add_argument("--lock", required=True, type=Path)
    run.add_argument("--output-directory", required=True, type=Path)
    run.add_argument("--run-id", required=True)

    replay = commands.add_parser("replay", help="replay one sealed E0 run")
    replay.add_argument("--run", required=True, type=Path)

    summarize = commands.add_parser(
        "summarize",
        help="verify and summarize one sealed E0 run",
    )
    summarize.add_argument("--run", required=True, type=Path)
    return parser


def _cli_output(value: Mapping[str, Any]) -> None:
    sys.stdout.write(_canonical_json_bytes(value).decode("utf-8") + "\n")


def _cli_error(
    *,
    command: str | None,
    error_type: str,
    message: str,
) -> None:
    sys.stderr.write(
        _canonical_json_bytes(
            {
                "command": command,
                "error_type": error_type,
                "message": message,
            }
        ).decode("utf-8")
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    materialized_argv = list(argv) if argv is not None else None
    command_hint = (
        materialized_argv[0]
        if materialized_argv
        else sys.argv[1]
        if len(sys.argv) > 1
        else None
    )
    try:
        args = _argument_parser().parse_args(materialized_argv)
    except _CLIArgumentError as error:
        _cli_error(
            command=command_hint,
            error_type="argument_error",
            message=str(error),
        )
        return 2

    try:
        if args.command == "sources":
            generated = generate_e0_source_runs(
                output_directory=args.output_directory,
                source_set_id=args.source_set_id,
            )
            output = {
                "command": "sources",
                "source_run_directories": {
                    status: str(path) for status, path in generated.items()
                },
            }
        elif args.command == "prepare":
            lock_path = prepare_e0_run(
                lock_directory=args.lock_directory,
                lock_id=args.lock_id,
                source_run_directories={
                    "completed": args.completed,
                    "failed": args.failed,
                    "budget_exhausted": args.budget_exhausted,
                    "max_cycles": args.max_cycles,
                },
            )
            output = {
                "command": "prepare",
                "lock_path": str(lock_path.resolve()),
            }
        elif args.command == "run":
            run_directory = execute_e0_run(
                lock_path=args.lock,
                output_directory=args.output_directory,
                run_id=args.run_id,
            )
            output = {
                "command": "run",
                "run_directory": str(run_directory.resolve()),
            }
        elif args.command == "replay":
            output = {
                "command": "replay",
                "report": replay_e0_run(args.run).to_dict(),
            }
        else:
            output = {
                "command": "summarize",
                "summary": summarize_e0_run(args.run),
            }
    except Exception as error:
        _cli_error(
            command=args.command,
            error_type=type(error).__name__,
            message=str(error),
        )
        return 1
    _cli_output(output)
    return 0


__all__ = [
    "E0ArtifactError",
    "E0ArtifactExistsError",
    "E0ReplayReport",
    "E0RunExecutionError",
    "E0RunFinalizedError",
    "E0RunIntegrityError",
    "E0RunStore",
    "execute_e0_run",
    "generate_e0_source_runs",
    "main",
    "prepare_e0_run",
    "replay_e0_run",
    "summarize_e0_run",
]


if __name__ == "__main__":
    raise SystemExit(main())
