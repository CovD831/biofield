"""Write-once offline run engineering shell for the MEAS0 pilot foundation.

The artifacts produced here remain explicitly non-claim-bearing: no live Judge,
human gold review, or preregistration approval is performed by this module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .meas0 import Meas0Arm
from .meas0_budget import BudgetEnforcer
from .meas0_pilot_runner import (
    PILOT_MUTATION_SEED,
    PILOT_RUNNER_VERSION,
    PilotArmResult,
    PilotCase,
    aggregate_pilot_foundation,
    load_pilot_mutation_manifest,
    materialize_pilot_cases,
    run_pilot_foundation,
)
from .resources import fixture_root as package_fixture_root
from .meas0_readiness import (
    ContractError,
    FormalReadinessBundle,
    FormalReadinessInputs,
    FormalReadinessReport,
    FormalReadinessValidator,
    arm_order_manifest,
    pilot_budget_policy,
    require_formal_readiness,
)


FOUNDATION_CLAIM_LIMIT = "pilot_foundation_only_not_a_formal_meas0_pilot_result"
FORMAL_CLAIM_LIMIT = "formal_meas0_pilot_package_not_a_gate_m_result"
PILOT_RUN_SHELL_VERSION = "meas0.pilot-run-shell.v11"
_EXPERIMENT_ID = "meas0"
_PHASE = "pilot"
_LOCK_SCHEMA_VERSION = 2
_DESIGN_BINDING_SCHEMA_VERSION = 1
_DESIGN_BINDING_KIND = "embedded_bytes_base64"


class PilotRunError(RuntimeError):
    """Base error for the MEAS0 pilot run shell."""


class PilotRunArtifactExistsError(PilotRunError, FileExistsError):
    """Raised instead of overwriting a lock, run, or artifact."""


class PilotRunFinalizedError(PilotRunError):
    """Raised when a caller tries to mutate a finalized run."""


class PilotRunIntegrityError(PilotRunError):
    """Raised when a lock, run seal, or deterministic replay disagrees."""


class PilotRunReadinessError(PilotRunError):
    """Raised before a formal run when readiness is incomplete or forged."""


class PilotExecutionMode(str, Enum):
    FOUNDATION = "foundation"
    FORMAL = "formal"


def _claim_limit(mode: PilotExecutionMode) -> str:
    return (
        FORMAL_CLAIM_LIMIT
        if mode is PilotExecutionMode.FORMAL
        else FOUNDATION_CLAIM_LIMIT
    )


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
        raise PilotRunError("artifact is not canonical JSON") from error


def _json_file_bytes(value: Any) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return _sha256(path.read_bytes())
    except OSError as error:
        raise PilotRunIntegrityError(f"cannot hash file: {path}") from error


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
        raise PilotRunError(f"{label} must be one safe path segment")
    return value


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise PilotRunError("artifact path must be a safe relative POSIX path")
    return path


def _ensure_below(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise PilotRunError("artifact path escapes the run directory") from error


def _atomic_create_bytes(path: Path, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise PilotRunError("atomic artifact content must be bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
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
            raise PilotRunArtifactExistsError(
                f"artifact already exists: {path.name}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise PilotRunIntegrityError(
            f"cannot read JSON artifact: {path.name}"
        ) from error
    return _json_object_bytes(content, path.name)


def _json_object_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PilotRunIntegrityError(f"cannot read JSON artifact: {label}") from error
    if not isinstance(value, dict):
        raise PilotRunIntegrityError(f"JSON artifact is not an object: {label}")
    return value


def _manifest_bundle_hash(file_hashes: Mapping[str, str]) -> str:
    payload = b"".join(
        path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n"
        for path, digest in sorted(file_hashes.items())
    )
    return _sha256(payload)


@dataclass(frozen=True)
class PilotReplayReport:
    verified: bool
    case_count: int
    arm_result_count: int
    replayed_result_count: int
    replay_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "case_count": self.case_count,
            "arm_result_count": self.arm_result_count,
            "replayed_result_count": self.replayed_result_count,
            "replay_hash": self.replay_hash,
        }


@dataclass(frozen=True)
class _VerifiedLockSnapshot:
    raw_bytes: bytes
    sha256: str
    lock: dict[str, Any]


class PilotRunStore:
    """Minimal nested, atomic, write-once artifact store."""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory.resolve()

    @classmethod
    def create(
        cls,
        output_directory: str | os.PathLike[str],
        run_id: str,
        *,
        comparison_block_id: str | None = None,
    ) -> PilotRunStore:
        safe_run_id = _safe_segment(run_id, "run_id")
        root = Path(output_directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        phase_directory = root / _EXPERIMENT_ID / _PHASE
        if any(
            item.exists() and item.is_symlink()
            for item in (root / _EXPERIMENT_ID, phase_directory)
        ):
            raise PilotRunError("run parent directories cannot be symbolic links")
        phase_directory.mkdir(parents=True, exist_ok=True)
        run_parent = phase_directory
        if comparison_block_id is not None:
            safe_block = _safe_segment(
                comparison_block_id,
                "comparison_block_id",
            )
            run_parent = phase_directory / safe_block
            if run_parent.exists() and run_parent.is_symlink():
                raise PilotRunError(
                    "comparison block directory cannot be a symbolic link"
                )
            run_parent.mkdir(parents=True, exist_ok=True)
        run_directory = run_parent / safe_run_id
        _ensure_below(run_directory, root)
        try:
            run_directory.mkdir()
        except FileExistsError as error:
            raise PilotRunArtifactExistsError(
                f"run already exists: {safe_run_id}"
            ) from error
        return cls(run_directory)

    @classmethod
    def open(cls, run_directory: str | os.PathLike[str]) -> PilotRunStore:
        path = Path(run_directory).expanduser().resolve()
        if not path.is_dir() or path.is_symlink():
            raise PilotRunIntegrityError("run directory is missing or invalid")
        return cls(path)

    @property
    def finalized(self) -> bool:
        return (self.run_directory / "seal.json").is_file()

    def write_bytes(self, relative_path: str, content: bytes) -> Path:
        if self.finalized:
            raise PilotRunFinalizedError("run is finalized and cannot be modified")
        relative = _safe_relative(relative_path)
        target = self.run_directory / relative
        _ensure_below(target, self.run_directory)
        if any(parent.is_symlink() for parent in target.parents if parent != target):
            raise PilotRunError("artifact parent cannot be a symbolic link")
        _atomic_create_bytes(target, content)
        return target

    def write_json(self, relative_path: str, value: Any) -> Path:
        return self.write_bytes(relative_path, _json_file_bytes(value))

    def finalize(
        self,
        *,
        status: str,
        metadata: Mapping[str, Any],
        execution_mode: PilotExecutionMode = PilotExecutionMode.FOUNDATION,
    ) -> dict[str, Any]:
        if self.finalized:
            raise PilotRunFinalizedError("run is already finalized")
        files = {
            path.relative_to(self.run_directory).as_posix(): _file_sha256(path)
            for path in sorted(self.run_directory.rglob("*"))
            if path.is_file() and path.name != "seal.json"
        }
        if not files:
            raise PilotRunError("cannot finalize an empty run")
        seal = {
            "schema_version": 1,
            "experiment_id": _EXPERIMENT_ID,
            "phase": _PHASE,
            "status": status,
            "claim_limit": _claim_limit(execution_mode),
            "execution_mode": execution_mode.value,
            "formal_pilot": execution_mode is PilotExecutionMode.FORMAL,
            "file_sha256": files,
            "artifact_bundle_hash": _manifest_bundle_hash(files),
            "metadata": dict(metadata),
        }
        _atomic_create_bytes(
            self.run_directory / "seal.json",
            _json_file_bytes(seal),
        )
        return seal


def _source_paths() -> dict[str, Path]:
    package = Path(__file__).parent
    return {
        "__init__.py": package / "__init__.py",
        "artifacts.py": package / "artifacts.py",
        "contracts.py": package / "contracts.py",
        "evidence_task.py": package / "evidence_task.py",
        "meas0.py": package / "meas0.py",
        "meas0_budget.py": package / "meas0_budget.py",
        "meas0_channel_order.py": package / "meas0_channel_order.py",
        "meas0_detection_oracle.py": package / "meas0_detection_oracle.py",
        "meas0_fixtures.py": package / "meas0_fixtures.py",
        "meas0_formal.py": package / "meas0_formal.py",
        "meas0_formal_derivation.py": package / "meas0_formal_derivation.py",
        "meas0_formal_lifecycle.py": package / "meas0_formal_lifecycle.py",
        "meas0_formal_metrics.py": package / "meas0_formal_metrics.py",
        "meas0_formal_outcomes.py": package / "meas0_formal_outcomes.py",
        "meas0_formal_run_store.py": package / "meas0_formal_run_store.py",
        "meas0_formal_runner.py": package / "meas0_formal_runner.py",
        "meas0_human.py": package / "meas0_human.py",
        "meas0_judge_probes.py": package / "meas0_judge_probes.py",
        "meas0_pilot_run.py": package / "meas0_pilot_run.py",
        "meas0_pilot_runner.py": package / "meas0_pilot_runner.py",
        "meas0_preflight.py": package / "meas0_preflight.py",
        "meas0_protected_artifacts.py": (package / "meas0_protected_artifacts.py"),
        "meas0_providers.py": package / "meas0_providers.py",
        "meas0_readiness.py": package / "meas0_readiness.py",
        "meas0_r1.py": package / "meas0_r1.py",
        "meas0_stage_cost.py": package / "meas0_stage_cost.py",
        "meas0_trust.py": package / "meas0_trust.py",
        "measurement.py": package / "measurement.py",
        "resources.py": package / "resources.py",
    }


def _source_hashes() -> dict[str, str]:
    return {name: _file_sha256(path) for name, path in _source_paths().items()}


def _fixture_hashes() -> dict[str, str]:
    root = package_fixture_root()
    relative_paths = (
        "r1/cold_chain_readiness/task.v1.json",
        "r1/cold_chain_readiness/answer_key.v1.json",
        "meas0/channel_order_ingest/task.v1.json",
        "meas0/channel_order_ingest/protected.v1.json",
        "meas0/pilot/mutations.v1.json",
        "meas0/pilot/mutations.v2.json",
        "meas0/pilot/mutations.v3.json",
        "meas0/pilot/mutations.v4.json",
        "meas0/pilot/mutations.v5.json",
        "meas0/pilot/mutations.v6.json",
        "meas0/pilot/mutations.v7.json",
    )
    return {relative: _file_sha256(root / relative) for relative in relative_paths}


def _evaluator_hashes(source_hashes: Mapping[str, str]) -> dict[str, str]:
    return {
        "cold_chain_readiness@1": source_hashes["meas0_r1.py"],
        "channel_order_ingest@1": source_hashes["meas0_channel_order.py"],
        "pilot_foundation@1": source_hashes["meas0_pilot_runner.py"],
    }


def _case_descriptor(case: PilotCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "task_id": case.task_id,
        "task_version": case.task_version,
        "fault_id": case.fault_id,
        "mutation_seed": case.mutation_seed,
        "manifest_sha256": case.manifest_sha256,
        "bundle_id": case.sealed_episode.bundle_id,
        "bundle_version": case.sealed_episode.bundle_version,
        "bundle_hash": case.sealed_episode.bundle_hash,
        "episode_hash": case.sealed_episode.episode_hash,
        "adapter_capability": case.adapter_capability,
        "native_task_sha256": (
            _sha256(case.native_task_bytes)
            if case.native_task_bytes is not None
            else None
        ),
        "native_measurement_plan_hash": (
            case.native_measurement_plan.plan_hash
            if case.native_measurement_plan is not None
            else None
        ),
        "native_unavailable_reason": case.native_unavailable_reason,
        "artifact_sha256": {
            evidence_id: _sha256(content)
            for evidence_id, content in case.artifacts.items
        },
        "gold_run_validity": case.gold_run_validity.value,
        "gold_status": (
            case.gold_status.value if case.gold_status is not None else None
        ),
        "accept_allowed": case.accept_allowed,
        "safety_violation": case.safety_violation,
    }


def _case_manifest(cases: Sequence[PilotCase]) -> tuple[dict[str, Any], ...]:
    return tuple(_case_descriptor(case) for case in cases)


def _case_manifest_hash(manifest: Sequence[Mapping[str, Any]]) -> str:
    return _sha256(_canonical_json_bytes(list(manifest)))


def _verify_lock_file(lock_path: Path) -> _VerifiedLockSnapshot:
    seal_path = lock_path.with_name("lock.seal.json")
    if not lock_path.is_file() or not seal_path.is_file():
        raise PilotRunIntegrityError("preregistration lock or lock seal is missing")
    seal = _read_json(seal_path)
    expected = seal.get("preregistration_lock_sha256")
    try:
        lock_bytes = lock_path.read_bytes()
    except OSError as error:
        raise PilotRunIntegrityError("cannot read preregistration lock") from error
    actual = _sha256(lock_bytes)
    if expected != actual:
        raise PilotRunIntegrityError("preregistration lock hash mismatch")
    lock = _json_object_bytes(lock_bytes, lock_path.name)
    schema_version = lock.get("schema_version")
    if type(schema_version) is not int or schema_version not in {
        1,
        _LOCK_SCHEMA_VERSION,
    }:
        raise PilotRunIntegrityError("unsupported lock schema version")
    if (
        seal.get("schema_version") != 1
        or lock.get("claim_limit") != FOUNDATION_CLAIM_LIMIT
        or lock.get("phase") != _PHASE
        or lock.get("case_count") != 36
        or lock.get("arm_case_count") != 180
    ):
        raise PilotRunIntegrityError("preregistration lock contract mismatch")
    order = arm_order_manifest()
    if lock.get("arm_order_manifest") != order.to_dict() or lock.get("arms") != list(
        order.resolved_arm_order
    ):
        raise PilotRunIntegrityError("locked arm order manifest mismatch")
    budget = pilot_budget_policy()
    if (
        lock.get("budget_policy") != budget.to_dict()
        or lock.get("budget_policy_hash") != budget.contract_hash
    ):
        raise PilotRunIntegrityError("locked budget policy mismatch")
    return _VerifiedLockSnapshot(
        raw_bytes=lock_bytes,
        sha256=actual,
        lock=lock,
    )


def _verified_design_document_bytes(
    lock: Mapping[str, Any],
) -> bytes:
    design_hash = lock.get("design_document_sha256")
    if not isinstance(design_hash, str):
        raise PilotRunIntegrityError("locked design document binding is malformed")
    schema_version = lock.get("schema_version")
    if type(schema_version) is not int or schema_version not in {
        1,
        _LOCK_SCHEMA_VERSION,
    }:
        raise PilotRunIntegrityError("unsupported lock schema version")
    if schema_version == 1:
        if "design_binding" in lock or "design_document_artifact" in lock:
            raise PilotRunIntegrityError("mixed design binding is forbidden")
        design_path = lock.get("design_document")
        if not isinstance(design_path, str):
            raise PilotRunIntegrityError("locked design document binding is malformed")
        try:
            path = Path(design_path)
            if not path.is_absolute():
                raise PilotRunIntegrityError(
                    "legacy design document path must be absolute"
                )
            content = path.read_bytes()
        except OSError as error:
            raise PilotRunIntegrityError(
                "locked design document hash mismatch"
            ) from error
    elif schema_version == _LOCK_SCHEMA_VERSION:
        if "design_document" in lock or "design_document_artifact" in lock:
            raise PilotRunIntegrityError("mixed design binding is forbidden")
        binding = lock.get("design_binding")
        expected_fields = {
            "schema_version",
            "kind",
            "source_name",
            "byte_count",
            "sha256",
            "content_base64",
        }
        if not isinstance(binding, Mapping) or set(binding) != expected_fields:
            raise PilotRunIntegrityError("locked design binding is malformed")
        if (
            type(binding.get("schema_version")) is not int
            or binding.get("schema_version") != _DESIGN_BINDING_SCHEMA_VERSION
            or binding.get("kind") != _DESIGN_BINDING_KIND
            or type(binding.get("byte_count")) is not int
            or binding.get("byte_count") < 0
            or binding.get("sha256") != design_hash
        ):
            raise PilotRunIntegrityError("locked design binding is malformed")
        source_name = binding.get("source_name")
        if (
            not isinstance(source_name, str)
            or source_name in {"", ".", ".."}
            or "/" in source_name
            or "\\" in source_name
            or "\0" in source_name
            or Path(source_name).name != source_name
        ):
            raise PilotRunIntegrityError("locked design binding is malformed")
        encoded = binding.get("content_base64")
        if not isinstance(encoded, str):
            raise PilotRunIntegrityError("locked design binding is malformed")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as error:
            raise PilotRunIntegrityError(
                "locked design binding is malformed"
            ) from error
        if len(content) != binding["byte_count"]:
            raise PilotRunIntegrityError("locked design binding is malformed")
        if base64.b64encode(content).decode("ascii") != encoded:
            raise PilotRunIntegrityError("locked design binding is malformed")
    if _sha256(content) != design_hash:
        raise PilotRunIntegrityError("locked design document hash mismatch")
    return content


def _verify_locked_sources(
    lock: Mapping[str, Any],
) -> bytes:
    if lock.get("source_hashes") != _source_hashes():
        raise PilotRunIntegrityError("locked source hash mismatch")
    if lock.get("fixture_hashes") != _fixture_hashes():
        raise PilotRunIntegrityError("locked fixture/manifest hash mismatch")
    source_hashes = lock["source_hashes"]
    if not isinstance(source_hashes, Mapping):
        raise PilotRunIntegrityError("locked source hashes are malformed")
    if lock.get("evaluator_hashes") != _evaluator_hashes(source_hashes):
        raise PilotRunIntegrityError("locked evaluator hash mismatch")
    design_bytes = _verified_design_document_bytes(lock)
    mutation_manifest = load_pilot_mutation_manifest()
    if lock.get("mutation_manifest_sha256") != mutation_manifest.source_sha256:
        raise PilotRunIntegrityError("locked mutation manifest hash mismatch")
    return design_bytes


def prepare_pilot_run(
    *,
    lock_directory: str | os.PathLike[str],
    lock_id: str,
    design_document: str | os.PathLike[str],
) -> Path:
    safe_lock_id = _safe_segment(lock_id, "lock_id")
    design_path = Path(design_document).expanduser().resolve()
    if not design_path.is_file():
        raise PilotRunError("design_document must be an existing file")
    try:
        design_bytes = design_path.read_bytes()
    except OSError as error:
        raise PilotRunError("design_document cannot be read") from error
    root = Path(lock_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / safe_lock_id
    _ensure_below(target, root)
    try:
        target.mkdir()
    except FileExistsError as error:
        raise PilotRunArtifactExistsError(
            f"lock already exists: {safe_lock_id}"
        ) from error

    cases = materialize_pilot_cases()
    manifest = load_pilot_mutation_manifest()
    case_manifest = _case_manifest(cases)
    source_hashes = _source_hashes()
    order = arm_order_manifest()
    budget = pilot_budget_policy()
    lock = {
        "schema_version": _LOCK_SCHEMA_VERSION,
        "lock_id": safe_lock_id,
        "experiment_id": _EXPERIMENT_ID,
        "phase": _PHASE,
        "implementation_version": PILOT_RUN_SHELL_VERSION,
        "foundation_runner_version": PILOT_RUNNER_VERSION,
        "claim_limit": FOUNDATION_CLAIM_LIMIT,
        "design_document_sha256": _sha256(design_bytes),
        "design_binding": {
            "schema_version": _DESIGN_BINDING_SCHEMA_VERSION,
            "kind": _DESIGN_BINDING_KIND,
            "source_name": design_path.name,
            "byte_count": len(design_bytes),
            "sha256": _sha256(design_bytes),
            "content_base64": base64.b64encode(design_bytes).decode("ascii"),
        },
        "mutation_seed": PILOT_MUTATION_SEED,
        "mutation_manifest_sha256": manifest.source_sha256,
        "source_hashes": source_hashes,
        "fixture_hashes": _fixture_hashes(),
        "evaluator_hashes": _evaluator_hashes(source_hashes),
        "task_bundle_hashes": {
            case.task_id: case.sealed_episode.bundle_hash for case in cases
        },
        "arms": list(order.resolved_arm_order),
        "arm_order_manifest": order.to_dict(),
        "budget_policy": budget.to_dict(),
        "budget_policy_hash": budget.contract_hash,
        "replay_count": 3,
        "judge_available": False,
        "human_review_available": False,
        "case_count": len(cases),
        "arm_case_count": len(cases) * len(Meas0Arm.all()),
        "case_manifest_hash": _case_manifest_hash(case_manifest),
        "case_manifest": list(case_manifest),
        "native_measurement_plans": {
            case.case_id: case.native_measurement_plan.to_dict()
            for case in cases
            if case.native_measurement_plan is not None
        },
        "native_measurement_plan_hashes": {
            case.case_id: case.native_measurement_plan.plan_hash
            for case in cases
            if case.native_measurement_plan is not None
        },
        "environment": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
    }
    lock_path = target / "preregistration.lock.json"
    try:
        _atomic_create_bytes(lock_path, _json_file_bytes(lock))
        _atomic_create_bytes(
            target / "lock.seal.json",
            _json_file_bytes(
                {
                    "schema_version": 1,
                    "lock_id": safe_lock_id,
                    "preregistration_lock_sha256": _file_sha256(lock_path),
                }
            ),
        )
    except Exception:
        # The directory is deliberately left visible if publication fails; a
        # caller must choose a new lock_id rather than overwrite partial state.
        raise
    return lock_path


def _verify_cases_against_lock(
    cases: Sequence[PilotCase],
    lock: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    manifest = _case_manifest(cases)
    if len(manifest) != 36:
        raise PilotRunIntegrityError("materialized case count differs from lock")
    if lock.get("case_manifest_hash") != _case_manifest_hash(manifest):
        raise PilotRunIntegrityError("materialized case manifest hash mismatch")
    if lock.get("case_manifest") != list(manifest):
        raise PilotRunIntegrityError("materialized case manifest differs from lock")
    expected_plans = {
        case.case_id: case.native_measurement_plan.to_dict()
        for case in cases
        if case.native_measurement_plan is not None
    }
    expected_plan_hashes = {
        case_id: value["plan_hash"] for case_id, value in expected_plans.items()
    }
    if (
        lock.get("native_measurement_plans") != expected_plans
        or lock.get("native_measurement_plan_hashes") != expected_plan_hashes
    ):
        raise PilotRunIntegrityError("native measurement plans differ from lock")
    return manifest


def _serialize_case(case: PilotCase) -> dict[str, Any]:
    return {
        **_case_descriptor(case),
        "sealed_episode": case.sealed_episode.to_dict(),
        "artifacts": [
            {
                "evidence_id": evidence_id,
                "sha256": _sha256(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
            for evidence_id, content in case.artifacts.items
        ],
    }


def _result_event(result: PilotArmResult, logical_index: int) -> dict[str, Any]:
    body = {
        "event_type": "pilot_foundation_arm_result",
        "logical_index": logical_index,
        "case_id": result.case_id,
        "task_id": result.task_id,
        "fault_id": result.fault_id,
        "arm": result.arm.value,
        "run_validity": result.run_validity.value,
        "automatic_status": (
            result.automatic_status.value
            if result.automatic_status is not None
            else None
        ),
        "unavailable": result.unavailable,
        "episode_hash": result.episode_hash,
        "result_hash": result.result_hash,
        "trace_hash": result.trace_hash,
    }
    return {
        "event_id": _sha256(_canonical_json_bytes(body)),
        **body,
    }


def _summary_payload(
    results: Sequence[PilotArmResult],
    metrics: Mapping[str, Mapping[str, int | float]],
    *,
    execution_mode: PilotExecutionMode,
) -> dict[str, Any]:
    return {
        "title": (
            "MEAS0 formal pilot run"
            if execution_mode is PilotExecutionMode.FORMAL
            else "MEAS0 offline pilot foundation run"
        ),
        "claim_limit": _claim_limit(execution_mode),
        "formal_pilot": execution_mode is PilotExecutionMode.FORMAL,
        "execution_mode": execution_mode.value,
        "case_count": 36,
        "arm_case_count": len(results),
        "sealed": True,
        "judge": "unavailable",
        "human_review": "unavailable",
        "arms": {key: dict(value) for key, value in metrics.items()},
    }


def _require_formal_execution_ready(
    *,
    source_lock_sha256: str,
    cases: Sequence[PilotCase],
    readiness_inputs: FormalReadinessInputs | None,
    readiness_report: FormalReadinessReport | None,
) -> None:
    if readiness_inputs is None or readiness_report is None:
        raise PilotRunReadinessError(
            "formal execution requires readiness inputs and report"
        )
    try:
        verified = FormalReadinessValidator().validate(readiness_inputs)
        if verified != readiness_report:
            raise PilotRunReadinessError(
                "formal readiness report does not match revalidated inputs"
            )
        require_formal_readiness(verified)
    except ContractError as error:
        raise PilotRunReadinessError(str(error)) from error
    case_scope = readiness_inputs.case_scope_manifest
    lock_bindings = readiness_inputs.formal_lock_bindings
    if (
        case_scope is None
        or lock_bindings is None
        or case_scope.case_ids != tuple(case.case_id for case in cases)
        or lock_bindings["preregistration_lock"] != source_lock_sha256
    ):
        raise PilotRunReadinessError(
            "formal readiness is not bound to the locked pilot cases"
        )
    expected_descriptors = {
        case.case_id: _sha256(_canonical_json_bytes(_case_descriptor(case)))
        for case in cases
    }
    if any(
        expected_descriptors.get(item.case_id) != item.case_descriptor_hash
        or item.native_adapter != (case.adapter_capability == "task_native")
        for item, case in zip(case_scope.cases, cases, strict=True)
    ):
        raise PilotRunReadinessError(
            "formal readiness case descriptors differ from materialized cases"
        )


def formal_artifact_payloads(
    readiness_inputs: FormalReadinessInputs,
) -> dict[str, Any]:
    """Build the target formal package without executing or mounting gold."""

    report = FormalReadinessValidator().validate(readiness_inputs)
    try:
        require_formal_readiness(report)
    except ContractError as error:
        raise PilotRunReadinessError(str(error)) from error
    layout = readiness_inputs.formal_artifact_layout
    manifest = readiness_inputs.gold_artifact_manifest
    mount = readiness_inputs.gold_mount_manifest
    if layout is None or manifest is None or mount is None:
        raise PilotRunReadinessError("formal artifact contracts are incomplete")
    return {
        "formal_artifact_layout.json": layout.to_dict(),
        layout.gold_manifest_path: manifest.to_dict(),
        layout.gold_mount_manifest_path: mount.to_dict(),
        "gold/records.json": {
            "records": [item.to_dict() for item in readiness_inputs.gold_records],
        },
        "gold/reviewer_records.json": {
            "records": [item.to_dict() for item in readiness_inputs.reviewer_records],
        },
        "gold/adjudication_records.json": {
            "records": [
                item.to_dict() for item in readiness_inputs.adjudication_records
            ],
        },
        "formal_execution_contract.json": {
            "execution_mode": PilotExecutionMode.FORMAL.value,
            "formal_pilot": True,
            "claim_limit": FORMAL_CLAIM_LIMIT,
            "gate_m_status": "pending_evaluation",
            "gold_mounted_to_runtime_principals": False,
        },
    }


def _write_task_bundle_artifacts(
    store: PilotRunStore,
    cases: Sequence[PilotCase],
) -> None:
    by_task: dict[str, PilotCase] = {}
    for case in cases:
        by_task.setdefault(case.task_id, case)
    for task_id, case in sorted(by_task.items()):
        bundle = case.task_measurement_bundle
        prefix = f"task_bundle/{task_id}"
        for filename, value in (
            ("task_frame.json", bundle.task_frame.to_dict()),
            ("goal_graph.json", bundle.goal_graph.to_dict()),
            ("requirement_graph.json", bundle.requirement_graph.to_dict()),
            ("measurement_graph.json", bundle.measurement_graph.to_dict()),
            (
                "acceptance_rule.json",
                {
                    "acceptance_rules": list(bundle.acceptance_rules),
                    "bundle_hash": bundle.bundle_hash,
                },
            ),
        ):
            store.write_json(f"{prefix}/{filename}", value)


def _json_artifact_or_ref(content: bytes | None) -> Any:
    if content is None:
        return None
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": _sha256(content),
        }


def _write_case_episode_artifacts(
    store: PilotRunStore,
    case: PilotCase,
) -> None:
    prefix = f"episode/cases/{case.case_id}"
    events = b"".join(
        _json_file_bytes(item.to_dict())
        for item in case.sealed_episode.episode_graph.evidence
    )
    store.write_bytes(f"{prefix}/events.ndjson", events)
    store.write_json(
        f"{prefix}/artifacts.json",
        {
            evidence_id: {
                "sha256": _sha256(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
            for evidence_id, content in case.artifacts.items
        },
    )
    store.write_json(
        f"{prefix}/state_before.json",
        _json_artifact_or_ref(case.artifacts.get("input:base_episode")),
    )
    store.write_json(
        f"{prefix}/state_after.json",
        _json_artifact_or_ref(case.artifacts.get("state:case")),
    )


def _write_arm_case_artifacts(
    store: PilotRunStore,
    result: PilotArmResult,
    budget: Any,
) -> None:
    prefix = f"arms/{result.arm.value}/cases/{result.case_id}"
    evaluation = result.to_dict()
    evaluation.update(
        run_validity=budget.run_validity.value,
        automatic_status=(
            budget.automatic_status.value
            if budget.automatic_status is not None
            else None
        ),
        budget_disposition_hash=budget.disposition_hash,
    )
    observation = {
        "case_id": result.case_id,
        "arm": result.arm.value,
        "run_validity": budget.run_validity.value,
        "status": (
            budget.automatic_status.value
            if budget.automatic_status is not None
            else None
        ),
        "evidence_refs": list(result.evidence_refs),
        "trace_hash": result.trace_hash,
    }
    store.write_bytes(
        f"{prefix}/observations.ndjson",
        _json_file_bytes(observation),
    )
    store.write_json(f"{prefix}/evaluation_result.json", evaluation)
    store.write_json(f"{prefix}/cost_vector.json", result.cost_vector.to_dict())
    store.write_bytes(f"{prefix}/stderr.log", b"")
    store.write_json(f"{prefix}/budget.json", budget.to_dict())
    if budget.failure is not None:
        store.write_json(f"{prefix}/failure.json", budget.failure.to_dict())


def execute_pilot_run(
    *,
    lock_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
    run_id: str,
    execution_mode: PilotExecutionMode | str = PilotExecutionMode.FOUNDATION,
    readiness_bundle_path: str | os.PathLike[str] | None = None,
    readiness_inputs: FormalReadinessInputs | None = None,
    readiness_report: FormalReadinessReport | None = None,
    comparison_block_id: str | None = None,
) -> Path:
    mode = (
        execution_mode
        if isinstance(execution_mode, PilotExecutionMode)
        else PilotExecutionMode(execution_mode)
    )
    if mode is PilotExecutionMode.FOUNDATION:
        if comparison_block_id is not None:
            raise PilotRunReadinessError(
                "foundation execution cannot use a formal comparison block"
            )
    elif comparison_block_id is None:
        raise PilotRunReadinessError("formal execution requires a comparison block")
    else:
        _safe_segment(comparison_block_id, "comparison_block_id")
    source_lock_path = Path(lock_path).expanduser().resolve()
    lock_snapshot = _verify_lock_file(source_lock_path)
    lock = lock_snapshot.lock
    _verify_locked_sources(lock)
    cases = materialize_pilot_cases()
    case_manifest = _verify_cases_against_lock(cases, lock)
    readiness_bundle: FormalReadinessBundle | None = None
    if mode is PilotExecutionMode.FORMAL:
        if (
            readiness_bundle_path is None
            or readiness_inputs is not None
            or readiness_report is not None
        ):
            raise PilotRunReadinessError(
                "formal execution requires one serialized readiness bundle"
            )
        try:
            readiness_bundle = FormalReadinessBundle.from_dict(
                _read_json(Path(readiness_bundle_path).expanduser().resolve())
            )
        except (PilotRunError, ContractError, OSError) as error:
            raise PilotRunReadinessError(
                "serialized formal readiness bundle is invalid"
            ) from error
        readiness_inputs = readiness_bundle.inputs
        readiness_report = readiness_bundle.report
        _require_formal_execution_ready(
            source_lock_sha256=lock_snapshot.sha256,
            cases=cases,
            readiness_inputs=readiness_inputs,
            readiness_report=readiness_report,
        )
        layout = readiness_inputs.formal_artifact_layout
        if layout is None or layout.comparison_block_id != comparison_block_id:
            raise PilotRunReadinessError(
                "formal comparison block differs from readiness layout"
            )
        raise PilotRunReadinessError(
            "formal execution backend is unavailable: the current runner "
            "does not execute qualified Judge or human-review arms"
        )

    store = PilotRunStore.create(
        output_directory,
        run_id,
        comparison_block_id=(
            comparison_block_id if mode is PilotExecutionMode.FORMAL else None
        ),
    )
    result_count = 0
    try:
        lock_bytes = lock_snapshot.raw_bytes
        store.write_bytes("preregistration.lock.json", lock_bytes)
        store.write_json(
            "config.json",
            {
                "schema_version": 1,
                "run_id": _safe_segment(run_id, "run_id"),
                "experiment_id": _EXPERIMENT_ID,
                "phase": _PHASE,
                "implementation_version": PILOT_RUN_SHELL_VERSION,
                "foundation_runner_version": PILOT_RUNNER_VERSION,
                "claim_limit": _claim_limit(mode),
                "execution_mode": mode.value,
                "formal_pilot": mode is PilotExecutionMode.FORMAL,
                "lock_sha256": _sha256(lock_bytes),
                "case_count": 36,
                "arm_case_count": 180,
                "replay_count": 3,
                "judge_available": (
                    mode is PilotExecutionMode.FORMAL
                    and readiness_inputs is not None
                    and readiness_inputs.judge_evidence is not None
                ),
                "human_review_available": (
                    mode is PilotExecutionMode.FORMAL
                    and readiness_inputs is not None
                    and readiness_inputs.operational_escalator_role_id is not None
                ),
            },
        )
        store.write_json("environment.json", lock["environment"])
        store.write_json(
            "arm_order_manifest.json",
            lock["arm_order_manifest"],
        )
        store.write_json("budget_policy.json", lock["budget_policy"])
        if mode is PilotExecutionMode.FORMAL and readiness_bundle is not None:
            store.write_json(
                "formal_readiness_inputs.json",
                readiness_bundle.inputs.to_dict(),
            )
            store.write_json(
                "formal_readiness_report.json",
                readiness_bundle.report.to_dict(),
            )
            store.write_json(
                "formal_readiness_bundle.json",
                readiness_bundle.to_dict(),
            )
            for path, payload in formal_artifact_payloads(
                readiness_bundle.inputs
            ).items():
                store.write_json(path, payload)
        store.write_json(
            "source_manifest.json",
            {
                "source_hashes": lock["source_hashes"],
                "fixture_hashes": lock["fixture_hashes"],
                "evaluator_hashes": lock["evaluator_hashes"],
                "design_binding_kind": (
                    lock.get("design_binding", {}).get("kind")
                    if isinstance(lock.get("design_binding"), Mapping)
                    else "legacy_absolute_path"
                ),
                "design_document_sha256": lock["design_document_sha256"],
                "mutation_manifest_sha256": lock["mutation_manifest_sha256"],
            },
        )
        store.write_json(
            "case_manifest.json",
            {
                "case_manifest_hash": _case_manifest_hash(case_manifest),
                "cases": list(case_manifest),
            },
        )
        _write_task_bundle_artifacts(store, cases)
        for case in cases:
            store.write_json(
                f"episode/cases/{case.case_id}.json",
                _serialize_case(case),
            )
            _write_case_episode_artifacts(store, case)

        results = run_pilot_foundation(
            cases,
            arm_order=lock["arms"],
        )
        if len(results) != 180:
            raise PilotRunIntegrityError(
                "foundation runner did not preserve the 180-result denominator"
            )
        budget_enforcer = BudgetEnforcer(pilot_budget_policy())
        budget_failures = 0
        for result in results:
            budget = budget_enforcer.enforce(
                case_id=result.case_id,
                task_id=result.task_id,
                arm=result.arm,
                run_validity=result.run_validity,
                automatic_status=result.automatic_status,
                cost=result.cost_vector,
            )
            store.write_json(
                f"arms/{result.arm.value}/results/{result.case_id}.json",
                result.to_dict(),
            )
            _write_arm_case_artifacts(store, result, budget)
            budget_failures += budget.failure is not None
            result_count += 1
        events = b"".join(
            _json_file_bytes(_result_event(result, index))
            for index, result in enumerate(results)
        )
        store.write_bytes("events.ndjson", events)
        metrics = aggregate_pilot_foundation(results)
        store.write_json(
            "metrics.json",
            {
                "case_count": len(cases),
                "arm_case_count": len(results),
                "arms": metrics,
                "failures_retained_in_denominator": True,
                "budget_failure_count": budget_failures,
                "stage_cost_vector": budget_enforcer.stage_cost.to_dict(),
            },
        )
        store.write_json(
            "summary.json",
            _summary_payload(
                results,
                metrics,
                execution_mode=mode,
            ),
        )
        store.finalize(
            status="completed",
            metadata={
                "case_count": len(cases),
                "arm_result_count": len(results),
                "lock_sha256": _sha256(lock_bytes),
                "case_manifest_hash": _case_manifest_hash(case_manifest),
            },
            execution_mode=mode,
        )
    except Exception as error:
        if not store.finalized:
            try:
                store.write_json(
                    "failure.json",
                    {
                        "error_type": type(error).__name__,
                        "message": str(error),
                        "arm_results_persisted": result_count,
                        "claim_limit": _claim_limit(mode),
                    },
                )
                store.finalize(
                    status="failed",
                    metadata={
                        "case_count": len(cases),
                        "arm_results_persisted": result_count,
                    },
                    execution_mode=mode,
                )
            except Exception:
                pass
        raise
    return store.run_directory


def _verify_run_seal(run_directory: Path) -> dict[str, Any]:
    seal_path = run_directory / "seal.json"
    if not seal_path.is_file():
        raise PilotRunIntegrityError("run is not finalized")
    seal = _read_json(seal_path)
    expected = seal.get("file_sha256")
    if not isinstance(expected, Mapping) or not all(
        isinstance(path, str) and isinstance(digest, str)
        for path, digest in expected.items()
    ):
        raise PilotRunIntegrityError("run seal file hashes are malformed")
    current_paths = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*")
        if path.is_file() and path.name != "seal.json"
    }
    if set(expected) != current_paths:
        raise PilotRunIntegrityError("sealed run file set mismatch")
    for relative_path, digest in expected.items():
        path = run_directory / _safe_relative(relative_path)
        if path.is_symlink() or _file_sha256(path) != digest:
            raise PilotRunIntegrityError(f"sealed run hash mismatch: {relative_path}")
    normalized_hashes = {str(path): str(digest) for path, digest in expected.items()}
    if seal.get("artifact_bundle_hash") != _manifest_bundle_hash(normalized_hashes):
        raise PilotRunIntegrityError("sealed run artifact bundle hash mismatch")
    config = _read_json(run_directory / "config.json")
    try:
        mode = PilotExecutionMode(config.get("execution_mode"))
    except ValueError as error:
        raise PilotRunIntegrityError("run execution mode is invalid") from error
    if (
        seal.get("claim_limit") != _claim_limit(mode)
        or seal.get("execution_mode") != mode.value
        or seal.get("formal_pilot") is not (mode is PilotExecutionMode.FORMAL)
        or config.get("claim_limit") != _claim_limit(mode)
        or config.get("formal_pilot") is not (mode is PilotExecutionMode.FORMAL)
        or seal.get("experiment_id") != _EXPERIMENT_ID
        or seal.get("phase") != _PHASE
    ):
        raise PilotRunIntegrityError("run seal identity mismatch")
    return seal


def _load_run_lock(
    run_directory: Path,
    seal: Mapping[str, Any],
) -> dict[str, Any]:
    lock_path = run_directory / "preregistration.lock.json"
    config = _read_json(run_directory / "config.json")
    try:
        lock_bytes = lock_path.read_bytes()
    except OSError as error:
        raise PilotRunIntegrityError("cannot read run lock") from error
    lock_sha256 = _sha256(lock_bytes)
    sealed_hashes = seal.get("file_sha256")
    if (
        not isinstance(sealed_hashes, Mapping)
        or config.get("lock_sha256") != lock_sha256
        or sealed_hashes.get("preregistration.lock.json") != lock_sha256
    ):
        raise PilotRunIntegrityError("run lock hash mismatch")
    lock = _json_object_bytes(lock_bytes, lock_path.name)
    if (
        lock.get("claim_limit") != FOUNDATION_CLAIM_LIMIT
        or lock.get("case_count") != 36
        or lock.get("arm_case_count") != 180
    ):
        raise PilotRunIntegrityError("run lock contract mismatch")
    _verify_locked_sources(lock)
    source_manifest = _read_json(run_directory / "source_manifest.json")
    expected_binding_kind = (
        lock.get("design_binding", {}).get("kind")
        if isinstance(lock.get("design_binding"), Mapping)
        else "legacy_absolute_path"
    )
    expected_source_manifest = {
        "source_hashes": lock.get("source_hashes"),
        "fixture_hashes": lock.get("fixture_hashes"),
        "evaluator_hashes": lock.get("evaluator_hashes"),
        "design_binding_kind": expected_binding_kind,
        "design_document_sha256": lock.get("design_document_sha256"),
        "mutation_manifest_sha256": lock.get("mutation_manifest_sha256"),
    }
    if source_manifest != expected_source_manifest:
        raise PilotRunIntegrityError(
            "run source manifest differs from preregistration lock"
        )
    if (
        _read_json(run_directory / "arm_order_manifest.json")
        != lock.get("arm_order_manifest")
        or _read_json(run_directory / "budget_policy.json") != lock.get("budget_policy")
        or _read_json(run_directory / "environment.json") != lock.get("environment")
    ):
        raise PilotRunIntegrityError(
            "run policy or environment differs from preregistration lock"
        )
    return lock


def _deterministic_result_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "evaluation_id",
        "case_id",
        "task_id",
        "fault_id",
        "arm",
        "bundle_hash",
        "episode_hash",
        "run_validity",
        "automatic_status",
        "post_escalation_status",
        "unavailable",
        "diagnostics",
        "evidence_refs",
        "trace_hash",
        "result_hash",
        "replay_hashes",
    )
    return {field: value.get(field) for field in fields}


def _verify_persisted_cases(
    run_directory: Path,
    cases: Sequence[PilotCase],
    lock: Mapping[str, Any],
) -> None:
    case_manifest = _verify_cases_against_lock(cases, lock)
    persisted_manifest = _read_json(run_directory / "case_manifest.json")
    if persisted_manifest.get("case_manifest_hash") != _case_manifest_hash(
        case_manifest
    ) or persisted_manifest.get("cases") != list(case_manifest):
        raise PilotRunIntegrityError("persisted case manifest mismatch")
    for case in cases:
        persisted = _read_json(
            run_directory / "episode" / "cases" / f"{case.case_id}.json"
        )
        if persisted != _serialize_case(case):
            raise PilotRunIntegrityError(
                f"persisted sealed case mismatch: {case.case_id}"
            )


def _verify_persisted_results(
    run_directory: Path,
    replayed: Sequence[PilotArmResult],
) -> tuple[str, ...]:
    result_hashes: list[str] = []
    for result in replayed:
        path = (
            run_directory
            / "arms"
            / result.arm.value
            / "results"
            / f"{result.case_id}.json"
        )
        persisted = _read_json(path)
        if _deterministic_result_projection(
            persisted
        ) != _deterministic_result_projection(result.to_dict()):
            raise PilotRunIntegrityError(
                f"deterministic replay result mismatch: "
                f"{result.case_id}/{result.arm.value}"
            )
        cost = persisted.get("cost_vector")
        if not isinstance(cost, Mapping) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in cost.values()
        ):
            raise PilotRunIntegrityError("persisted CostVector is malformed")
        result_hashes.append(result.result_hash)
    return tuple(result_hashes)


def _verify_budget_artifacts(
    run_directory: Path,
    replayed: Sequence[PilotArmResult],
) -> None:
    for result in replayed:
        prefix = run_directory / "arms" / result.arm.value / "cases" / result.case_id
        budget = _read_json(prefix / "budget.json")
        declared_hash = budget.pop("disposition_hash", None)
        if (
            declared_hash != _sha256(_canonical_json_bytes(budget))
            or budget.get("case_id") != result.case_id
            or budget.get("task_id") != result.task_id
            or budget.get("arm") != result.arm.value
            or budget.get("cost") != _read_json(prefix / "cost_vector.json")
            or budget.get("retained_in_denominator") is not True
        ):
            raise PilotRunIntegrityError(
                f"budget artifact mismatch: {result.case_id}/{result.arm.value}"
            )
        failure_path = prefix / "failure.json"
        failure = budget.get("failure")
        if (failure is None) != (not failure_path.exists()):
            raise PilotRunIntegrityError("budget failure artifact set mismatch")
        if failure is not None and _read_json(failure_path) != failure:
            raise PilotRunIntegrityError("budget failure artifact mismatch")


def replay_pilot_run(
    run_directory: str | os.PathLike[str],
) -> PilotReplayReport:
    store = PilotRunStore.open(run_directory)
    seal = _verify_run_seal(store.run_directory)
    if seal.get("execution_mode") == PilotExecutionMode.FORMAL.value:
        raise PilotRunReadinessError(
            "formal replay backend is unavailable; foundation replay cannot "
            "validate a formal package"
        )
    if seal.get("status") != "completed":
        raise PilotRunIntegrityError("only completed foundation runs can replay")
    lock = _load_run_lock(store.run_directory, seal)
    cases = materialize_pilot_cases()
    _verify_persisted_cases(store.run_directory, cases, lock)
    replayed = run_pilot_foundation(cases, arm_order=lock["arms"])
    if len(replayed) != 180:
        raise PilotRunIntegrityError("replay did not preserve 180 results")
    result_hashes = _verify_persisted_results(store.run_directory, replayed)
    _verify_budget_artifacts(store.run_directory, replayed)
    try:
        event_lines = (
            (store.run_directory / "events.ndjson")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    except OSError as error:
        raise PilotRunIntegrityError("cannot read persisted events") from error
    if len(event_lines) != 180:
        raise PilotRunIntegrityError("persisted event denominator is not 180")
    for index, (line, result) in enumerate(zip(event_lines, replayed, strict=True)):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise PilotRunIntegrityError("persisted event is not JSON") from error
        if event != _result_event(result, index):
            raise PilotRunIntegrityError("persisted event replay mismatch")
    replay_hash = _sha256(
        _canonical_json_bytes(
            {
                "artifact_bundle_hash": seal["artifact_bundle_hash"],
                "case_episode_hashes": [
                    case.sealed_episode.episode_hash for case in cases
                ],
                "result_hashes": list(result_hashes),
            }
        )
    )
    return PilotReplayReport(
        verified=True,
        case_count=len(cases),
        arm_result_count=180,
        replayed_result_count=len(replayed),
        replay_hash=replay_hash,
    )


def summarize_pilot_run(
    run_directory: str | os.PathLike[str],
) -> dict[str, Any]:
    store = PilotRunStore.open(run_directory)
    seal = _verify_run_seal(store.run_directory)
    if seal.get("execution_mode") == PilotExecutionMode.FORMAL.value:
        raise PilotRunReadinessError(
            "formal summarize backend is unavailable; foundation summary "
            "cannot validate a formal package"
        )
    if seal.get("status") != "completed":
        raise PilotRunIntegrityError("only completed foundation runs can summarize")
    summary = _read_json(store.run_directory / "summary.json")
    if (
        summary.get("claim_limit") != FOUNDATION_CLAIM_LIMIT
        or summary.get("formal_pilot") is not False
        or summary.get("execution_mode") != PilotExecutionMode.FOUNDATION.value
        or summary.get("case_count") != 36
        or summary.get("arm_case_count") != 180
    ):
        raise PilotRunIntegrityError("foundation summary contract mismatch")
    return summary


__all__ = [
    "FOUNDATION_CLAIM_LIMIT",
    "FORMAL_CLAIM_LIMIT",
    "PILOT_RUN_SHELL_VERSION",
    "PilotExecutionMode",
    "PilotReplayReport",
    "PilotRunArtifactExistsError",
    "PilotRunError",
    "PilotRunFinalizedError",
    "PilotRunIntegrityError",
    "PilotRunReadinessError",
    "PilotRunStore",
    "execute_pilot_run",
    "formal_artifact_payloads",
    "prepare_pilot_run",
    "replay_pilot_run",
    "summarize_pilot_run",
]
