from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from biofield.meas0_preflight import (
    REQUIRED_PREFLIGHT_COMMAND_IDS,
    AttestationKind,
    CommandSpec,
    ExecutorResult,
    MountDeclaration,
    PreflightAssessment,
    PreflightContractError,
    capture_preflight_evidence,
    validate_production_preflight,
)


class FakeExecutor:
    def __init__(
        self,
        results: dict[str, ExecutorResult],
    ) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> ExecutorResult:
        self.calls.append(argv)
        return self.results[argv[0]]


def _commands() -> tuple[CommandSpec, ...]:
    return tuple(
        CommandSpec(command_id=command_id, argv=(command_id, "--probe"))
        for command_id in REQUIRED_PREFLIGHT_COMMAND_IDS
    )


def _executor(*, failed: str | None = None) -> FakeExecutor:
    return FakeExecutor(
        {
            command_id: ExecutorResult(
                exit_code=1 if command_id == failed else 0,
                stdout=f"{command_id}:ok\n".encode(),
                stderr=(
                    b"injected failure\n"
                    if command_id == failed
                    else b""
                ),
            )
            for command_id in REQUIRED_PREFLIGHT_COMMAND_IDS
        }
    )


def _mounts() -> tuple[MountDeclaration, ...]:
    return (
        MountDeclaration(
            mount_id="protected-evaluator",
            principal="evaluator",
            source_path="/sealed/protected",
            target_path="/sandbox/protected",
            mounted=True,
            read_only=True,
            contains_hidden_gold=False,
        ),
        MountDeclaration(
            mount_id="hidden-gold-evaluator",
            principal="evaluator",
            source_path="/sealed/gold",
            target_path="/sandbox/gold",
            mounted=False,
            read_only=True,
            contains_hidden_gold=True,
        ),
    )


def _capture(
    *,
    executor: FakeExecutor | None = None,
    mounts: tuple[MountDeclaration, ...] | None = None,
):
    return capture_preflight_evidence(
        attestation_kind=AttestationKind.TEST_ONLY,
        executor_id="fake-executor-v1",
        commands=_commands(),
        executor=executor or _executor(),
        environment={
            "python": "3.13.9",
            "platform": "offline-test",
        },
        dependencies={
            "biofield": "editable-test",
            "jsonschema": "4.25.0",
        },
        mounts=mounts or _mounts(),
        network_policy="deny_subject_allow_frozen_judge",
        process_policy="separate_processes_required",
        acl_audit_log=b"acl audit: no hidden gold runtime grants\n",
    )


def test_fake_executor_capture_derives_hashes_and_never_self_attests_pass() -> None:
    executor = _executor()
    evidence = _capture(executor=executor)
    assessment = PreflightAssessment.from_evidence(evidence)

    assert executor.calls == [item.argv for item in _commands()]
    assert evidence.attestation_kind is AttestationKind.TEST_ONLY
    assert len(evidence.environment_sha256) == 64
    assert len(evidence.dependency_manifest_sha256) == 64
    assert evidence.acl_audit_log_sha256 == hashlib.sha256(
        evidence.acl_audit_log
    ).hexdigest()
    first = evidence.command_records[0]
    assert first.stdout_sha256 == hashlib.sha256(first.stdout).hexdigest()
    assert first.stderr_sha256 == hashlib.sha256(first.stderr).hexdigest()
    assert assessment.technical_checks_passed is True
    assert assessment.production_eligible is False
    assert assessment.passed is False
    with pytest.raises(TypeError):
        PreflightAssessment(passed=True)  # type: ignore[call-arg]
    with pytest.raises(PreflightContractError, match="test_only"):
        validate_production_preflight(evidence)


def test_command_failure_is_derived_from_raw_exit_and_stream_records() -> None:
    evidence = _capture(executor=_executor(failed="network_policy_probe"))
    assessment = PreflightAssessment.from_evidence(evidence)

    failed = next(
        item
        for item in evidence.command_records
        if item.command_id == "network_policy_probe"
    )
    assert failed.exit_code == 1
    assert failed.stderr == b"injected failure\n"
    assert assessment.checks["commands_succeeded"] is False
    assert assessment.technical_checks_passed is False
    assert assessment.passed is False


def test_mount_network_process_and_acl_results_are_derived_fail_closed() -> None:
    writable = replace(_mounts()[0], read_only=False)
    gold_mounted = replace(_mounts()[1], mounted=True)
    evidence = _capture(mounts=(writable, gold_mounted))
    assessment = PreflightAssessment.from_evidence(evidence)

    assert assessment.checks["protected_mounts_read_only"] is False
    assert assessment.checks["hidden_gold_unmounted"] is False
    assert assessment.passed is False

    policy_failure = replace(
        _capture(),
        network_policy="allow_all",
        process_policy="same_process",
        acl_audit_log=b"",
    )
    policy_assessment = PreflightAssessment.from_evidence(policy_failure)
    assert policy_assessment.checks["network_policy_enforced"] is False
    assert policy_assessment.checks["process_policy_enforced"] is False
    assert policy_assessment.checks["acl_audit_present"] is False


def test_production_validation_rejects_missing_raw_records() -> None:
    production = replace(
        _capture(),
        attestation_kind=AttestationKind.PRODUCTION,
        command_records=(),
    )
    with pytest.raises(PreflightContractError, match="raw command records"):
        validate_production_preflight(production)

    no_acl = replace(
        _capture(),
        attestation_kind=AttestationKind.PRODUCTION,
        acl_audit_log=b"",
    )
    with pytest.raises(PreflightContractError, match="ACL audit"):
        validate_production_preflight(no_acl)

