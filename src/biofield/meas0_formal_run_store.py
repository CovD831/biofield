"""Atomic write-once lifecycle package for typed MEAS0 formal runs.

The store is deliberately post-readiness and post-execution.  It accepts only
an already-derived ``FormalContractRun`` and its post-run outcome evidence
bundle.  It provides no CLI flag, fake backend, network adapter, readiness
override, or scientific Gate decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .meas0_detection_oracle import DetectionOracleManifest
from .meas0_formal_derivation import OracleBoundArmCaseOutcome
from .meas0_formal_outcomes import FormalOutcomeEvidenceBundle
from .meas0_formal_runner import (
    FormalContractRun,
    FormalPilotPlan,
)


FORMAL_RUN_STORE_VERSION = "meas0.formal-run-store.v1"
FORMAL_RUN_CONFIG_SCHEMA = "meas0.formal-run-config.v1"
FORMAL_RUN_ARTIFACT_INDEX_SCHEMA = "meas0.formal-artifact-index.v1"
FORMAL_RUN_SUMMARY_SCHEMA = "meas0.formal-run-summary.v1"
FORMAL_RUN_SEAL_SCHEMA = "meas0.formal-run-seal.v1"
_SUMMARY_FACTORY_TOKEN = object()
_SNAPSHOT_FACTORY_TOKEN = object()


class FormalRunPackageIntegrityError(RuntimeError):
    """Raised when lifecycle publication or replay fails closed."""


class FormalRunPackageExistsError(
    FormalRunPackageIntegrityError,
    FileExistsError,
):
    """Raised instead of overwriting a lifecycle package."""


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
        raise FormalRunPackageIntegrityError(
            "formal lifecycle value is not canonical JSON"
        ) from error


def _json_file_bytes(value: Any) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalRunPackageIntegrityError(f"{label} must be lowercase SHA-256")
    return value


def _safe_segment(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
        or Path(value).name != value
    ):
        raise FormalRunPackageIntegrityError(f"{label} must be one safe path segment")
    return value


def _absolute(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().absolute()


def _reject_symlink_ancestry(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise FormalRunPackageIntegrityError(
                "formal lifecycle path ancestry cannot contain a symbolic link"
            )
        if current.parent == current:
            return
        current = current.parent


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise FormalRunPackageIntegrityError(
            "cannot fsync formal lifecycle directory"
        ) from error


def _atomic_write_json(path: Path, value: Any) -> None:
    _reject_symlink_ancestry(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestry(path.parent)
    file_bytes = _json_file_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(file_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FormalRunPackageExistsError(
                f"formal lifecycle artifact already exists: {path.name}"
            ) from error
        except OSError as error:
            raise FormalRunPackageIntegrityError(
                "cannot atomically publish formal lifecycle artifact"
            ) from error
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise FormalRunPackageIntegrityError(
            f"cannot hash formal lifecycle artifact: {path.name}"
        ) from error


def _manifest_hash(file_hashes: Mapping[str, str]) -> str:
    return _canonical_hash(
        {
            "schema": FORMAL_RUN_SEAL_SCHEMA,
            "file_sha256": dict(sorted(file_hashes.items())),
        }
    )


def _expected_file_set() -> set[str]:
    return {
        "config.json",
        "plan.json",
        "authorization.json",
        "ledgers/pre.json",
        "ledgers/final.json",
        "artifacts/index.json",
        *(f"artifacts/{index:03d}.json" for index in range(180)),
        "run.json",
        "outcome_evidence.json",
        "summary.json",
    }


def _config(
    *,
    package_id: str,
    plan: FormalPilotPlan,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
) -> dict[str, Any]:
    return {
        "schema": FORMAL_RUN_CONFIG_SCHEMA,
        "store_version": FORMAL_RUN_STORE_VERSION,
        "package_id": package_id,
        "claim_scope": outcome_evidence.seal.claim_scope,
        "formal_result": run.formal_result,
        "test_only": outcome_evidence.seal.test_only,
        "formal_eligible": outcome_evidence.seal.formal_eligible,
        "run_hash": run.run_hash,
        "plan_hash": plan.plan_hash,
        "authorization_hash": run.authorization.authorization_hash,
        "source_lock_hash": outcome_evidence.seal.source_lock_hash,
        "outcome_bundle_hash": outcome_evidence.bundle_hash,
    }


def _artifact_index(run: FormalContractRun) -> dict[str, Any]:
    return {
        "schema": FORMAL_RUN_ARTIFACT_INDEX_SCHEMA,
        "artifact_count": len(run.artifacts),
        "artifacts": [
            {
                "execution_index": artifact.execution_index,
                "case_id": artifact.case_id,
                "arm_id": artifact.arm_id,
                "artifact_hash": artifact.artifact_hash,
                "path": f"artifacts/{artifact.execution_index:03d}.json",
            }
            for artifact in run.artifacts
        ],
    }


@dataclass(frozen=True)
class FormalRunLifecycleSummary:
    schema: str
    package_id: str
    run_hash: str
    plan_hash: str
    authorization_hash: str
    source_lock_hash: str
    outcome_bundle_hash: str
    case_count: int
    arm_case_count: int
    artifact_count: int
    stage_stopped: bool
    test_only: bool
    formal_eligible: bool
    summary_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _SUMMARY_FACTORY_TOKEN:
            raise FormalRunPackageIntegrityError(
                "formal lifecycle summaries require typed derivation"
            )
        if (
            self.schema != FORMAL_RUN_SUMMARY_SCHEMA
            or self.case_count != 36
            or self.arm_case_count != 180
            or self.artifact_count != 180
            or not isinstance(self.stage_stopped, bool)
            or not isinstance(self.test_only, bool)
            or not isinstance(self.formal_eligible, bool)
            or self.test_only is self.formal_eligible
        ):
            raise FormalRunPackageIntegrityError(
                "formal lifecycle summary is malformed"
            )
        for value, label in (
            (self.run_hash, "summary run_hash"),
            (self.plan_hash, "summary plan_hash"),
            (self.authorization_hash, "summary authorization_hash"),
            (self.source_lock_hash, "summary source_lock_hash"),
            (self.outcome_bundle_hash, "summary outcome_bundle_hash"),
            (self.summary_hash, "summary_hash"),
        ):
            _hash(value, label)
        if self.summary_hash != _canonical_hash(self._body()):
            raise FormalRunPackageIntegrityError(
                "formal lifecycle summary hash mismatch"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "package_id": self.package_id,
            "run_hash": self.run_hash,
            "plan_hash": self.plan_hash,
            "authorization_hash": self.authorization_hash,
            "source_lock_hash": self.source_lock_hash,
            "outcome_bundle_hash": self.outcome_bundle_hash,
            "case_count": self.case_count,
            "arm_case_count": self.arm_case_count,
            "artifact_count": self.artifact_count,
            "stage_stopped": self.stage_stopped,
            "test_only": self.test_only,
            "formal_eligible": self.formal_eligible,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "summary_hash": self.summary_hash}


def _summary(
    *,
    package_id: str,
    plan: FormalPilotPlan,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
) -> FormalRunLifecycleSummary:
    body = {
        "schema": FORMAL_RUN_SUMMARY_SCHEMA,
        "package_id": package_id,
        "run_hash": run.run_hash,
        "plan_hash": plan.plan_hash,
        "authorization_hash": run.authorization.authorization_hash,
        "source_lock_hash": outcome_evidence.seal.source_lock_hash,
        "outcome_bundle_hash": outcome_evidence.bundle_hash,
        "case_count": run.case_count,
        "arm_case_count": run.arm_case_count,
        "artifact_count": len(run.artifacts),
        "stage_stopped": run.stage_stopped,
        "test_only": outcome_evidence.seal.test_only,
        "formal_eligible": outcome_evidence.seal.formal_eligible,
    }
    return FormalRunLifecycleSummary(
        **body,
        summary_hash=_canonical_hash(body),
        _factory_token=_SUMMARY_FACTORY_TOKEN,
    )


def _validate_typed_sources(
    *,
    plan: FormalPilotPlan,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
) -> None:
    if not isinstance(plan, FormalPilotPlan):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle requires a FormalPilotPlan"
        )
    if not isinstance(run, FormalContractRun):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle requires a FormalContractRun"
        )
    if not isinstance(outcome_evidence, FormalOutcomeEvidenceBundle):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle requires typed outcome evidence"
        )
    if (
        run.authorization.plan_hash != plan.plan_hash
        or run.stage_cost_pre_ledger != plan.stage_cost_pre_ledger
        or outcome_evidence.seal.run_hash != run.run_hash
        or outcome_evidence.seal.authorization_hash
        != run.authorization.authorization_hash
        or outcome_evidence.package.plan_hash != plan.plan_hash
        or outcome_evidence.package.run_hash != run.run_hash
        or outcome_evidence.seal.test_only is not outcome_evidence.package.test_only
        or outcome_evidence.seal.formal_eligible
        is not outcome_evidence.package.formal_eligible
        or outcome_evidence.seal.formal_eligible is not run.formal_result
    ):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle typed source ancestry is inconsistent"
        )


def _logical_values(
    *,
    package_id: str,
    plan: FormalPilotPlan,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
) -> dict[str, Any]:
    summary = _summary(
        package_id=package_id,
        plan=plan,
        run=run,
        outcome_evidence=outcome_evidence,
    )
    values: dict[str, Any] = {
        "config.json": _config(
            package_id=package_id,
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
        ),
        "plan.json": plan.to_dict(),
        "authorization.json": run.authorization.to_dict(),
        "ledgers/pre.json": run.stage_cost_pre_ledger.to_dict(),
        "ledgers/final.json": run.stage_cost_final_ledger.to_dict(),
        "artifacts/index.json": _artifact_index(run),
        "run.json": run.to_dict(),
        "outcome_evidence.json": outcome_evidence.to_dict(),
        "summary.json": summary.to_dict(),
    }
    values.update(
        {
            f"artifacts/{artifact.execution_index:03d}.json": artifact.to_dict()
            for artifact in run.artifacts
        }
    )
    if set(values) != _expected_file_set():
        raise FormalRunPackageIntegrityError(
            "formal lifecycle logical file set is incomplete"
        )
    return values


def _seal(
    *,
    package_id: str,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
    file_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema": FORMAL_RUN_SEAL_SCHEMA,
        "store_version": FORMAL_RUN_STORE_VERSION,
        "package_id": package_id,
        "run_hash": run.run_hash,
        "authorization_hash": run.authorization.authorization_hash,
        "source_lock_hash": outcome_evidence.seal.source_lock_hash,
        "outcome_bundle_hash": outcome_evidence.bundle_hash,
        "file_sha256": dict(sorted(file_hashes.items())),
        "package_hash": _manifest_hash(file_hashes),
    }


def _read_json_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalRunPackageIntegrityError(
            f"formal lifecycle artifact is not JSON: {label}"
        ) from error
    if not isinstance(value, dict):
        raise FormalRunPackageIntegrityError(
            f"formal lifecycle artifact must be an object: {label}"
        )
    return value


def _verified_bytes(
    package_directory: str | os.PathLike[str],
) -> tuple[Path, dict[str, bytes], dict[str, Any]]:
    directory = _absolute(package_directory)
    _reject_symlink_ancestry(directory)
    if not directory.is_dir():
        raise FormalRunPackageIntegrityError(
            "formal lifecycle package directory is missing"
        )
    seal_path = directory / "seal.json"
    if not seal_path.is_file() or seal_path.is_symlink():
        raise FormalRunPackageIntegrityError(
            "formal lifecycle package is partial or missing its seal"
        )
    try:
        seal_bytes = seal_path.read_bytes()
    except OSError as error:
        raise FormalRunPackageIntegrityError(
            "cannot read formal lifecycle seal"
        ) from error
    seal = _read_json_bytes(seal_bytes, "seal.json")
    expected_seal_keys = {
        "schema",
        "store_version",
        "package_id",
        "run_hash",
        "authorization_hash",
        "source_lock_hash",
        "outcome_bundle_hash",
        "file_sha256",
        "package_hash",
    }
    if set(seal) != expected_seal_keys:
        raise FormalRunPackageIntegrityError("formal lifecycle seal keys are invalid")
    file_hashes = seal["file_sha256"]
    if (
        seal["schema"] != FORMAL_RUN_SEAL_SCHEMA
        or seal["store_version"] != FORMAL_RUN_STORE_VERSION
        or not isinstance(file_hashes, Mapping)
        or set(file_hashes) != _expected_file_set()
        or seal["package_hash"] != _manifest_hash(file_hashes)
    ):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle seal or file set is invalid"
        )
    entries = tuple(directory.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle package cannot contain a symbolic link"
        )
    actual_files = {
        path.relative_to(directory).as_posix() for path in entries if path.is_file()
    }
    if actual_files != {*_expected_file_set(), "seal.json"}:
        raise FormalRunPackageIntegrityError(
            "formal lifecycle package file set differs from its seal"
        )
    actual_directories = {
        path.relative_to(directory).as_posix() for path in entries if path.is_dir()
    }
    if actual_directories != {"artifacts", "ledgers"}:
        raise FormalRunPackageIntegrityError(
            "formal lifecycle package directory set is invalid"
        )
    contents: dict[str, bytes] = {}
    for relative_path, expected_hash in file_hashes.items():
        _hash(expected_hash, f"sealed file hash {relative_path}")
        path = directory / relative_path
        if path.is_symlink() or not path.is_file():
            raise FormalRunPackageIntegrityError(
                f"formal lifecycle sealed artifact is missing: {relative_path}"
            )
        try:
            content = path.read_bytes()
        except OSError as error:
            raise FormalRunPackageIntegrityError(
                f"cannot read formal lifecycle artifact: {relative_path}"
            ) from error
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise FormalRunPackageIntegrityError(
                f"formal lifecycle artifact hash mismatch: {relative_path}"
            )
        contents[relative_path] = content
    return directory, contents, seal


@dataclass(frozen=True)
class FormalRunPackageSnapshot:
    package_directory: Path
    package_id: str
    run_hash: str
    plan_hash: str
    authorization_hash: str
    source_lock_hash: str
    outcome_bundle_hash: str
    package_hash: str
    file_hashes: tuple[tuple[str, str], ...]
    summary: FormalRunLifecycleSummary
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _SNAPSHOT_FACTORY_TOKEN:
            raise FormalRunPackageIntegrityError(
                "formal lifecycle snapshots require verified sealed bytes"
            )


@dataclass(frozen=True)
class FormalRunReplayReport:
    verified: bool
    package_id: str
    run_hash: str
    outcome_bundle_hash: str
    file_count: int
    replay_hash: str


def _verify_sources(
    *,
    package_directory: str | os.PathLike[str],
    plan: FormalPilotPlan,
    run: FormalContractRun,
    outcome_evidence: FormalOutcomeEvidenceBundle,
    oracle_manifest: DetectionOracleManifest,
    outcomes: Sequence[OracleBoundArmCaseOutcome],
) -> FormalRunPackageSnapshot:
    _validate_typed_sources(
        plan=plan,
        run=run,
        outcome_evidence=outcome_evidence,
    )
    if not isinstance(oracle_manifest, DetectionOracleManifest):
        raise FormalRunPackageIntegrityError(
            "formal lifecycle replay requires a typed oracle manifest"
        )
    directory, contents, seal = _verified_bytes(package_directory)
    package_id = _safe_segment(seal["package_id"], "sealed package_id")
    if directory.name != package_id:
        raise FormalRunPackageIntegrityError(
            "formal lifecycle directory identity differs from its seal"
        )
    expected_values = _logical_values(
        package_id=package_id,
        plan=plan,
        run=run,
        outcome_evidence=outcome_evidence,
    )
    for relative_path, expected_value in expected_values.items():
        if contents[relative_path] != _json_file_bytes(expected_value):
            raise FormalRunPackageIntegrityError(
                f"formal lifecycle artifact disagrees with typed ancestry: "
                f"{relative_path}"
            )
    persisted_outcome = _read_json_bytes(
        contents["outcome_evidence.json"],
        "outcome_evidence.json",
    )
    restored_outcome = FormalOutcomeEvidenceBundle.from_dict(
        persisted_outcome,
        run=run,
        oracle_manifest=oracle_manifest,
        outcomes=outcomes,
        source_lock_hash=outcome_evidence.seal.source_lock_hash,
    )
    if restored_outcome != outcome_evidence:
        raise FormalRunPackageIntegrityError(
            "formal lifecycle outcome evidence does not reverify"
        )
    expected_seal = _seal(
        package_id=package_id,
        run=run,
        outcome_evidence=outcome_evidence,
        file_hashes=seal["file_sha256"],
    )
    if seal != expected_seal:
        raise FormalRunPackageIntegrityError(
            "formal lifecycle seal disagrees with typed ancestry"
        )
    summary = _summary(
        package_id=package_id,
        plan=plan,
        run=run,
        outcome_evidence=outcome_evidence,
    )
    return FormalRunPackageSnapshot(
        package_directory=directory,
        package_id=package_id,
        run_hash=run.run_hash,
        plan_hash=plan.plan_hash,
        authorization_hash=run.authorization.authorization_hash,
        source_lock_hash=outcome_evidence.seal.source_lock_hash,
        outcome_bundle_hash=outcome_evidence.bundle_hash,
        package_hash=seal["package_hash"],
        file_hashes=tuple(sorted(seal["file_sha256"].items())),
        summary=summary,
        _factory_token=_SNAPSHOT_FACTORY_TOKEN,
    )


class FormalRunPackageStore:
    """Write, read, replay, and summarize one sealed formal lifecycle."""

    @classmethod
    def publish(
        cls,
        *,
        output_directory: str | os.PathLike[str],
        package_id: str,
        plan: FormalPilotPlan,
        run: FormalContractRun,
        outcome_evidence: FormalOutcomeEvidenceBundle,
    ) -> Path:
        _validate_typed_sources(
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
        )
        safe_package_id = _safe_segment(package_id, "package_id")
        root = _absolute(output_directory)
        _reject_symlink_ancestry(root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise FormalRunPackageIntegrityError(
                "cannot create formal lifecycle output directory"
            ) from error
        _reject_symlink_ancestry(root)
        package_directory = root / safe_package_id
        try:
            package_directory.mkdir()
        except FileExistsError as error:
            raise FormalRunPackageExistsError(
                f"formal lifecycle package already exists: {safe_package_id}"
            ) from error
        except OSError as error:
            raise FormalRunPackageIntegrityError(
                "cannot create formal lifecycle package directory"
            ) from error
        values = _logical_values(
            package_id=safe_package_id,
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
        )
        try:
            for relative_path in sorted(values):
                _atomic_write_json(
                    package_directory / relative_path,
                    values[relative_path],
                )
            file_hashes = {
                relative_path: _file_hash(package_directory / relative_path)
                for relative_path in sorted(values)
            }
            _atomic_write_json(
                package_directory / "seal.json",
                _seal(
                    package_id=safe_package_id,
                    run=run,
                    outcome_evidence=outcome_evidence,
                    file_hashes=file_hashes,
                ),
            )
            _fsync_directory(package_directory)
            _fsync_directory(root)
        except FormalRunPackageIntegrityError:
            raise
        except OSError as error:
            raise FormalRunPackageIntegrityError(
                "formal lifecycle publish was interrupted"
            ) from error
        return package_directory

    @classmethod
    def read(
        cls,
        package_directory: str | os.PathLike[str],
        *,
        plan: FormalPilotPlan,
        run: FormalContractRun,
        outcome_evidence: FormalOutcomeEvidenceBundle,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
    ) -> FormalRunPackageSnapshot:
        return _verify_sources(
            package_directory=package_directory,
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
            oracle_manifest=oracle_manifest,
            outcomes=outcomes,
        )

    @classmethod
    def replay(
        cls,
        package_directory: str | os.PathLike[str],
        *,
        plan: FormalPilotPlan,
        run: FormalContractRun,
        outcome_evidence: FormalOutcomeEvidenceBundle,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
    ) -> FormalRunReplayReport:
        snapshot = cls.read(
            package_directory,
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
            oracle_manifest=oracle_manifest,
            outcomes=outcomes,
        )
        replay_body = {
            "package_id": snapshot.package_id,
            "run_hash": snapshot.run_hash,
            "outcome_bundle_hash": snapshot.outcome_bundle_hash,
            "package_hash": snapshot.package_hash,
            "file_hashes": dict(snapshot.file_hashes),
        }
        return FormalRunReplayReport(
            verified=True,
            package_id=snapshot.package_id,
            run_hash=snapshot.run_hash,
            outcome_bundle_hash=snapshot.outcome_bundle_hash,
            file_count=len(snapshot.file_hashes),
            replay_hash=_canonical_hash(replay_body),
        )

    @classmethod
    def summarize(
        cls,
        package_directory: str | os.PathLike[str],
        *,
        plan: FormalPilotPlan,
        run: FormalContractRun,
        outcome_evidence: FormalOutcomeEvidenceBundle,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
    ) -> FormalRunLifecycleSummary:
        return cls.read(
            package_directory,
            plan=plan,
            run=run,
            outcome_evidence=outcome_evidence,
            oracle_manifest=oracle_manifest,
            outcomes=outcomes,
        ).summary


@dataclass(frozen=True)
class FormalShellExecution:
    run: FormalContractRun
    outcome_evidence: FormalOutcomeEvidenceBundle

    def __post_init__(self) -> None:
        if not isinstance(self.run, FormalContractRun) or not isinstance(
            self.outcome_evidence,
            FormalOutcomeEvidenceBundle,
        ):
            raise FormalRunPackageIntegrityError(
                "formal shell backend result is malformed"
            )


@runtime_checkable
class FormalShellBackend(Protocol):
    """Injectable Python-only execution boundary; no readiness bypass surface."""

    def execute(self, plan: FormalPilotPlan) -> FormalShellExecution: ...


def run_formal_shell_lifecycle(
    *,
    plan: FormalPilotPlan,
    backend: FormalShellBackend,
    output_directory: str | os.PathLike[str],
    package_id: str,
) -> Path:
    """Execute an injected typed backend and publish its immutable lifecycle."""

    if not isinstance(plan, FormalPilotPlan):
        raise FormalRunPackageIntegrityError(
            "formal shell lifecycle requires a FormalPilotPlan"
        )
    if not isinstance(backend, FormalShellBackend):
        raise FormalRunPackageIntegrityError(
            "formal shell lifecycle requires a typed Python backend"
        )
    execution = backend.execute(plan)
    if not isinstance(execution, FormalShellExecution):
        raise FormalRunPackageIntegrityError(
            "formal shell backend returned an invalid result"
        )
    return FormalRunPackageStore.publish(
        output_directory=output_directory,
        package_id=package_id,
        plan=plan,
        run=execution.run,
        outcome_evidence=execution.outcome_evidence,
    )


__all__ = [
    "FORMAL_RUN_STORE_VERSION",
    "FormalRunLifecycleSummary",
    "FormalRunPackageExistsError",
    "FormalRunPackageIntegrityError",
    "FormalRunPackageSnapshot",
    "FormalRunPackageStore",
    "FormalRunReplayReport",
    "FormalShellBackend",
    "FormalShellExecution",
    "run_formal_shell_lifecycle",
]
