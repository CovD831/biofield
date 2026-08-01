"""Offline evidence contracts for a future formal MEAS0 preflight.

This module does not establish operating-system isolation.  It captures raw
records from an injected executor and derives hashes and check results from
those records.  Test-only attestations are useful for contract tests but are
never production-eligible.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Protocol


REQUIRED_PREFLIGHT_COMMAND_IDS = (
    "environment_probe",
    "dependency_probe",
    "mount_table_probe",
    "network_policy_probe",
    "process_isolation_probe",
    "acl_audit_probe",
)
EXPECTED_NETWORK_POLICY = "deny_subject_allow_frozen_judge"
EXPECTED_PROCESS_POLICY = "separate_processes_required"


class PreflightContractError(ValueError):
    """A preflight record is malformed or insufficient for production."""


class AttestationKind(str, Enum):
    TEST_ONLY = "test_only"
    PRODUCTION = "production"


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
        raise PreflightContractError(
            "preflight value is not canonical JSON"
        ) from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreflightContractError(f"{label} must be non-empty text")
    return value


def _absolute_path(value: object, label: str) -> str:
    text = _text(value, label)
    path = PurePosixPath(text)
    if not path.is_absolute() or ".." in path.parts:
        raise PreflightContractError(
            f"{label} must be an absolute normalized POSIX path"
        )
    return text


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.command_id, "command_id")
        normalized = tuple(_text(item, "command argv") for item in self.argv)
        if not normalized:
            raise PreflightContractError("command argv cannot be empty")
        object.__setattr__(self, "argv", normalized)


@dataclass(frozen=True)
class ExecutorResult:
    exit_code: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if isinstance(self.exit_code, bool) or not isinstance(
            self.exit_code,
            int,
        ):
            raise PreflightContractError("exit code must be an integer")
        if not isinstance(self.stdout, bytes) or not isinstance(
            self.stderr,
            bytes,
        ):
            raise PreflightContractError(
                "executor stdout and stderr must be raw bytes"
            )


class PreflightExecutor(Protocol):
    def run(self, argv: tuple[str, ...]) -> ExecutorResult: ...


@dataclass(frozen=True)
class CommandRecord:
    command_id: str
    argv: tuple[str, ...]
    exit_code: int
    stdout: bytes
    stderr: bytes

    @classmethod
    def capture(
        cls,
        spec: CommandSpec,
        result: ExecutorResult,
    ) -> CommandRecord:
        if not isinstance(spec, CommandSpec) or not isinstance(
            result,
            ExecutorResult,
        ):
            raise PreflightContractError(
                "command capture requires typed raw inputs"
            )
        return cls(
            command_id=spec.command_id,
            argv=spec.argv,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    @property
    def stdout_sha256(self) -> str:
        return _sha256(self.stdout)

    @property
    def stderr_sha256(self) -> str:
        return _sha256(self.stderr)

    @property
    def raw_record_sha256(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout_hex": self.stdout.hex(),
            "stderr_hex": self.stderr.hex(),
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
        }


@dataclass(frozen=True)
class MountDeclaration:
    mount_id: str
    principal: str
    source_path: str
    target_path: str
    mounted: bool
    read_only: bool
    contains_hidden_gold: bool

    def __post_init__(self) -> None:
        _text(self.mount_id, "mount_id")
        _text(self.principal, "mount principal")
        _absolute_path(self.source_path, "mount source_path")
        _absolute_path(self.target_path, "mount target_path")
        for field_name in (
            "mounted",
            "read_only",
            "contains_hidden_gold",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise PreflightContractError(
                    f"{field_name} must be boolean"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class PreflightEvidence:
    attestation_kind: AttestationKind
    executor_id: str
    command_records: tuple[CommandRecord, ...]
    environment: tuple[tuple[str, str], ...]
    dependencies: tuple[tuple[str, str], ...]
    mounts: tuple[MountDeclaration, ...]
    network_policy: str
    process_policy: str
    acl_audit_log: bytes

    def __post_init__(self) -> None:
        try:
            kind = (
                self.attestation_kind
                if isinstance(self.attestation_kind, AttestationKind)
                else AttestationKind(self.attestation_kind)
            )
        except ValueError as error:
            raise PreflightContractError(
                "attestation kind is invalid"
            ) from error
        object.__setattr__(self, "attestation_kind", kind)
        _text(self.executor_id, "executor_id")
        object.__setattr__(
            self,
            "command_records",
            tuple(self.command_records),
        )
        object.__setattr__(self, "environment", tuple(self.environment))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "mounts", tuple(self.mounts))
        _text(self.network_policy, "network policy")
        _text(self.process_policy, "process policy")
        if not isinstance(self.acl_audit_log, bytes):
            raise PreflightContractError("ACL audit log must be raw bytes")

    @property
    def environment_sha256(self) -> str:
        return _sha256(_canonical_json_bytes(dict(self.environment)))

    @property
    def dependency_manifest_sha256(self) -> str:
        return _sha256(_canonical_json_bytes(dict(self.dependencies)))

    @property
    def acl_audit_log_sha256(self) -> str:
        return _sha256(self.acl_audit_log)

    @property
    def evidence_sha256(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attestation_kind": self.attestation_kind.value,
            "executor_id": self.executor_id,
            "command_records": [
                {
                    **item.to_dict(),
                    "raw_record_sha256": item.raw_record_sha256,
                }
                for item in self.command_records
            ],
            "environment": dict(self.environment),
            "environment_sha256": self.environment_sha256,
            "dependencies": dict(self.dependencies),
            "dependency_manifest_sha256": (
                self.dependency_manifest_sha256
            ),
            "mounts": [item.to_dict() for item in self.mounts],
            "network_policy": self.network_policy,
            "process_policy": self.process_policy,
            "acl_audit_log_hex": self.acl_audit_log.hex(),
            "acl_audit_log_sha256": self.acl_audit_log_sha256,
        }


@dataclass(frozen=True, init=False)
class PreflightAssessment:
    evidence_sha256: str
    _checks: tuple[tuple[str, bool], ...]
    attestation_kind: AttestationKind

    @classmethod
    def from_evidence(
        cls,
        evidence: PreflightEvidence,
    ) -> PreflightAssessment:
        if not isinstance(evidence, PreflightEvidence):
            raise PreflightContractError(
                "assessment requires typed preflight evidence"
            )
        command_ids = tuple(
            item.command_id for item in evidence.command_records
        )
        records_complete = (
            len(command_ids) == len(set(command_ids))
            and set(command_ids) == set(REQUIRED_PREFLIGHT_COMMAND_IDS)
        )
        protected = tuple(
            item
            for item in evidence.mounts
            if item.mounted and not item.contains_hidden_gold
        )
        hidden_gold = tuple(
            item for item in evidence.mounts if item.contains_hidden_gold
        )
        checks = {
            "raw_command_records_complete": records_complete,
            "commands_succeeded": records_complete
            and all(
                item.exit_code == 0
                for item in evidence.command_records
            ),
            "environment_record_present": bool(evidence.environment),
            "dependency_record_present": bool(evidence.dependencies),
            "mount_declarations_present": bool(evidence.mounts),
            "protected_mounts_read_only": bool(protected)
            and all(item.read_only for item in protected),
            "hidden_gold_unmounted": bool(hidden_gold)
            and all(not item.mounted for item in hidden_gold),
            "network_policy_enforced": (
                evidence.network_policy == EXPECTED_NETWORK_POLICY
            ),
            "process_policy_enforced": (
                evidence.process_policy == EXPECTED_PROCESS_POLICY
            ),
            "acl_audit_present": bool(evidence.acl_audit_log),
        }
        result = object.__new__(cls)
        object.__setattr__(
            result,
            "evidence_sha256",
            evidence.evidence_sha256,
        )
        object.__setattr__(result, "_checks", tuple(sorted(checks.items())))
        object.__setattr__(
            result,
            "attestation_kind",
            evidence.attestation_kind,
        )
        return result

    @property
    def checks(self) -> dict[str, bool]:
        return dict(self._checks)

    @property
    def technical_checks_passed(self) -> bool:
        return all(value for _, value in self._checks)

    @property
    def production_eligible(self) -> bool:
        return self.attestation_kind is AttestationKind.PRODUCTION

    @property
    def passed(self) -> bool:
        return self.technical_checks_passed and self.production_eligible

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_sha256": self.evidence_sha256,
            "attestation_kind": self.attestation_kind.value,
            "checks": self.checks,
            "technical_checks_passed": self.technical_checks_passed,
            "production_eligible": self.production_eligible,
            "passed": self.passed,
        }


def _normalized_mapping(
    value: Mapping[str, str],
    label: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise PreflightContractError(f"{label} must be a mapping")
    items = tuple(
        sorted(
            (
                _text(key, f"{label} key"),
                _text(item, f"{label} value"),
            )
            for key, item in value.items()
        )
    )
    if len({key for key, _ in items}) != len(items):
        raise PreflightContractError(f"{label} keys must be unique")
    return items


def capture_preflight_evidence(
    *,
    attestation_kind: AttestationKind,
    executor_id: str,
    commands: Sequence[CommandSpec],
    executor: PreflightExecutor,
    environment: Mapping[str, str],
    dependencies: Mapping[str, str],
    mounts: Sequence[MountDeclaration],
    network_policy: str,
    process_policy: str,
    acl_audit_log: bytes,
) -> PreflightEvidence:
    materialized = tuple(commands)
    command_ids = tuple(item.command_id for item in materialized)
    if (
        len(command_ids) != len(set(command_ids))
        or set(command_ids) != set(REQUIRED_PREFLIGHT_COMMAND_IDS)
    ):
        raise PreflightContractError(
            "preflight commands must exactly cover required command IDs"
        )
    records = tuple(
        CommandRecord.capture(spec, executor.run(spec.argv))
        for spec in materialized
    )
    return PreflightEvidence(
        attestation_kind=attestation_kind,
        executor_id=executor_id,
        command_records=records,
        environment=_normalized_mapping(environment, "environment"),
        dependencies=_normalized_mapping(dependencies, "dependencies"),
        mounts=tuple(mounts),
        network_policy=network_policy,
        process_policy=process_policy,
        acl_audit_log=acl_audit_log,
    )


def validate_production_preflight(
    evidence: PreflightEvidence,
) -> PreflightAssessment:
    if not isinstance(evidence, PreflightEvidence):
        raise PreflightContractError(
            "production validation requires typed preflight evidence"
        )
    if evidence.attestation_kind is AttestationKind.TEST_ONLY:
        raise PreflightContractError(
            "test_only attestation cannot satisfy production validation"
        )
    command_ids = tuple(
        item.command_id for item in evidence.command_records
    )
    if (
        len(command_ids) != len(set(command_ids))
        or set(command_ids) != set(REQUIRED_PREFLIGHT_COMMAND_IDS)
    ):
        raise PreflightContractError(
            "production validation requires all raw command records"
        )
    if not evidence.acl_audit_log:
        raise PreflightContractError(
            "production validation requires the raw ACL audit log"
        )
    assessment = PreflightAssessment.from_evidence(evidence)
    if not assessment.passed:
        failed = ",".join(
            name for name, passed in assessment.checks.items() if not passed
        )
        raise PreflightContractError(
            f"production preflight checks failed: {failed}"
        )
    return assessment


__all__ = [
    "EXPECTED_NETWORK_POLICY",
    "EXPECTED_PROCESS_POLICY",
    "REQUIRED_PREFLIGHT_COMMAND_IDS",
    "AttestationKind",
    "CommandRecord",
    "CommandSpec",
    "ExecutorResult",
    "MountDeclaration",
    "PreflightAssessment",
    "PreflightContractError",
    "PreflightEvidence",
    "PreflightExecutor",
    "capture_preflight_evidence",
    "validate_production_preflight",
]
