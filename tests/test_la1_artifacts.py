from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

import biofield.la1_artifacts as la1_module
from biofield.artifacts import RunFinalizedError
from biofield.la1_artifacts import (
    LA1ArtifactIntegrityError,
    LA1RunExecutionError,
    execute_la1_run,
    main,
    prepare_la1_run,
    replay_la1_run,
    summarize_la1_run,
)
from biofield.local_runtime import HarnessRuntimeEvent


EXPECTED_COST_FIELDS = {
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
}


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_success_run_persists_frozen_metrics_and_replays(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="success-1",
        scenario="success",
    )
    executed = execute_la1_run(run_directory)

    assert executed.status == "completed"
    assert set(path.name for path in run_directory.iterdir()) >= {
        "artifacts",
        "config.json",
        "events.jsonl",
        "finalization.json",
        "metrics.json",
        "summary.md",
    }
    config = _read_json(run_directory / "config.json")
    assert config["schema_version"] == "la1.config.v1"
    assert config["runner_version"] == "la1-artifact-runner-v5"
    assert config["environment"]["model"] == "none-scripted-agents"
    assert len(config["environment"]["git_commit"]) >= 7
    assert config["source_sha256"]
    assert config["scenario_parameters"]["agent_count"] == 3
    assert config["scenario_parameters"]["private_state_values"] == (
        "omitted-hash-only"
    )

    metrics = _read_json(run_directory / "metrics.json")
    assert metrics["schema_version"] == "la1.metrics.v2"
    assert metrics["scenario"] == "success"
    assert metrics["contract_validity"]["rate"] == 1.0
    assert metrics["contract_validity"]["denominator"] > 0
    assert metrics["illegal_rejection"]["status"] == "not_applicable"
    assert metrics["refusal_recovery"]["rate"] == 1.0
    assert metrics["communication"]["messages"] == 1
    assert metrics["communication"]["bytes"] > 0
    assert metrics["communication"]["resource_cost"] == {"tokens": 3.0}
    assert metrics["communication"]["cost_per_accepted_contribution"] == {"tokens": 3.0}
    assert metrics["cost_vector"]["communication_tokens"] == 3.0
    assert metrics["state_update_provenance"]["rate"] == 1.0
    assert metrics["ledger_conservation"]["conserved"] is True
    assert len(metrics["public_terminal_hash"]) == 64
    assert set(metrics["cost_vector"]) == EXPECTED_COST_FIELDS

    replayed = replay_la1_run(run_directory)
    assert replayed.status == "completed"
    assert replayed.terminal_projection_sha256 == (metrics["public_terminal_hash"])
    assert replayed.metrics == metrics


def test_prepare_seals_exact_config_before_execution(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="locked-config-1",
        scenario="success",
    )
    assert (run_directory / "artifacts" / "config_lock.json").is_file()
    assert (run_directory / "artifacts" / "config_seal.json").is_file()
    lock_path = run_directory / "artifacts" / "config_lock.json"
    seal = _read_json(run_directory / "artifacts" / "config_seal.json")
    assert (
        seal["config_lock_sha256"] == hashlib.sha256(lock_path.read_bytes()).hexdigest()
    )

    config_path = run_directory / "config.json"
    config = _read_json(config_path)
    config["environment"]["model"] = "forged-model"
    config_path.write_text(
        json.dumps(config, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="prepared config hash mismatch",
    ):
        execute_la1_run(run_directory)


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (
        ("schema_version", 2),
        ("experiment_id", "forged-experiment"),
        ("run_id", "forged-run"),
        ("reason", "forged reason"),
    ),
)
def test_replay_rejects_forged_finalization_identity_and_reason(
    tmp_path: Path,
    field_name: str,
    forged_value: object,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id=f"finalization-{field_name}",
        scenario="success",
    )
    execute_la1_run(run_directory)
    path = run_directory / "finalization.json"
    finalization = _read_json(path)
    finalization[field_name] = forged_value
    path.write_text(
        json.dumps(finalization, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="finalization contract",
    ):
        replay_la1_run(run_directory)


def test_failure_recovery_run_seals_checkpoint_and_reorganization_metrics(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="failure-recovery-1",
        scenario="failure_recovery",
    )
    execute_la1_run(run_directory)
    metrics = _read_json(run_directory / "metrics.json")

    assert metrics["scenario"] == "failure_recovery"
    assert metrics["reorganization_count"] == 1
    assert metrics["completion_recovery_cycles"] == {
        "completed_commitments": 1,
        "failed_or_cancelled_commitments": 1,
        "recovery_cycles": 1,
        "total_commitment_cycles": 2,
    }
    assert metrics["cost_vector"]["retry_count"] == 1
    assert metrics["ledger_conservation"]["conserved"] is True
    assert (run_directory / "artifacts" / "organization_snapshot.json").is_file()
    assert (run_directory / "artifacts" / "failure_checkpoint.json").is_file()
    assert (
        replay_la1_run(run_directory).terminal_projection_sha256
        == metrics["public_terminal_hash"]
    )


def test_summary_api_freezes_all_protocol_metric_denominators(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="summary-1",
        scenario="success",
    )
    execution = execute_la1_run(run_directory)
    summary = summarize_la1_run(
        scenario="success",
        events=execution.events,
        organization_snapshot=execution.organization_snapshot,
        ledger_totals=execution.ledger_totals,
        terminal_projection_sha256=execution.terminal_projection_sha256,
        run_budget={"tokens": 100.0},
        wall_time_ms=0.0,
        cpu_time_ms=0.0,
        deterministic_check_calls=1,
    )

    assert set(summary["metric_definitions"]) == {
        "contract_validity",
        "admission_rejection_by_reason",
        "illegal_rejection",
        "time_to_first_commitment",
        "duplicate_effort",
        "refusal_recovery",
        "communication",
        "state_update_provenance",
        "public_terminal_hash",
        "ledger_conservation",
        "residual_over_cycles",
        "reorganization_count",
        "completion_recovery_cycles",
        "organization_snapshot_stats",
        "cost_vector",
    }
    assert summary["admission_rejection_by_reason"]["decision_denominator"] > 0
    assert summary["admission_rejection_by_reason"]["by_reason"]
    assert summary["duplicate_effort"]["count"] == 0
    assert summary["time_to_first_commitment"]["unit"] == "public_events"
    assert summary["residual_over_cycles"]
    assert summary["organization_snapshot_stats"]["active_agents"] == 3


def test_refusal_recovery_requires_later_different_commitment() -> None:
    def event(
        index: int,
        event_type: str,
        payload: dict[str, object],
    ) -> HarnessRuntimeEvent:
        return HarnessRuntimeEvent(
            event_id=f"event-{index}",
            event_type=event_type,
            event_schema_version=1,
            public_state_revision=index,
            causal_parent_ids=(f"event-{index - 1}",) if index else (),
            payload=payload,
            payload_sha256=la1_module._sha256(payload),
        )

    earlier_commitment = event(
        0,
        "gate_commitment",
        {"commitment": {"agent_id": "agent-b"}},
    )
    refusal = event(
        1,
        "gate_refusal",
        {"refusal": {"agent_id": "agent-a"}},
    )
    assert la1_module._refusal_recovery((earlier_commitment, refusal))["rate"] == 0.0
    later_commitment = event(
        2,
        "gate_takeover_commitment",
        {"commitment": {"agent_id": "agent-b"}},
    )
    assert (
        la1_module._refusal_recovery((earlier_commitment, refusal, later_commitment))[
            "rate"
        ]
        == 1.0
    )


def test_finalized_run_is_write_protected(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="finalized-1",
        scenario="success",
    )
    execute_la1_run(run_directory)

    with pytest.raises(RunFinalizedError, match="finalized"):
        execute_la1_run(run_directory)


def test_replay_rejects_tampered_sealed_event(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="tamper-1",
        scenario="success",
    )
    execute_la1_run(run_directory)
    events_path = run_directory / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8").replace(
            '"event_type":"gate_terminal"',
            '"event_type":"forged_terminal"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="sealed file hash mismatch",
    ):
        replay_la1_run(run_directory)


def test_replay_rejects_tampered_transitively_sealed_artifact(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="artifact-tamper-1",
        scenario="failure_recovery",
    )
    execute_la1_run(run_directory)
    organization_path = run_directory / "artifacts" / "organization_snapshot.json"
    organization_path.write_text(
        organization_path.read_text(encoding="utf-8").replace(
            '"builder_version":"failure-reorganization-v1"',
            '"builder_version":"forged-runtime-v1"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="sealed artifact hash mismatch",
    ):
        replay_la1_run(run_directory)


def test_failed_execution_is_sealed_retained_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="failed-1",
        scenario="success",
    )

    def fail(_config):
        raise RuntimeError("injected offline executor failure")

    monkeypatch.setattr("biofield.la1_artifacts._execute_scenario", fail)
    with pytest.raises(
        LA1RunExecutionError,
        match="injected offline executor failure",
    ):
        execute_la1_run(run_directory)

    finalization = _read_json(run_directory / "finalization.json")
    metrics = _read_json(run_directory / "metrics.json")
    assert finalization["status"] == "failed"
    assert metrics["run_validity"] == "invalid-run"
    assert metrics["failure"]["error_type"] == "RuntimeError"
    assert metrics["failure"]["excluded_from_denominator"] is False
    replayed = replay_la1_run(run_directory)
    assert replayed.status == "failed"
    assert replayed.metrics == metrics
    assert set(metrics["cost_vector"]) == EXPECTED_COST_FIELDS


def test_failed_metrics_cannot_add_a_self_rehashed_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="failed-claim-injection",
        scenario="success",
    )

    def fail(_config):
        raise RuntimeError("injected claim attack fixture")

    monkeypatch.setattr("biofield.la1_artifacts._execute_scenario", fail)
    with pytest.raises(LA1RunExecutionError):
        execute_la1_run(run_directory)

    metrics_path = run_directory / "metrics.json"
    metrics = _read_json(metrics_path)
    metrics["gate1_passed"] = True
    metrics_path.write_text(
        json.dumps(metrics, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    finalization_path = run_directory / "finalization.json"
    finalization = _read_json(finalization_path)
    finalization["file_sha256"]["metrics.json"] = hashlib.sha256(
        metrics_path.read_bytes()
    ).hexdigest()
    finalization_path.write_text(
        json.dumps(finalization, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="failure metrics contract",
    ):
        replay_la1_run(run_directory)


def test_summary_cannot_be_rewritten_with_a_self_rehashed_claim(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="summary-claim-injection",
        scenario="success",
    )
    execute_la1_run(run_directory)
    summary_path = run_directory / "summary.md"
    summary_path.write_text(
        summary_path.read_text(encoding="utf-8") + "\nGate 1: passed\n",
        encoding="utf-8",
    )
    finalization_path = run_directory / "finalization.json"
    finalization = _read_json(finalization_path)
    finalization["file_sha256"]["summary.md"] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()
    finalization_path.write_text(
        json.dumps(finalization, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="summary does not replay",
    ):
        replay_la1_run(run_directory)


@pytest.mark.parametrize("failure_point", ("artifact_hashes", "summary"))
def test_late_execution_failure_is_sealed_retained_and_replayable(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id=f"late-failed-{failure_point}",
        scenario="success",
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"injected {failure_point} failure")

    target = (
        "_artifact_hashes"
        if failure_point == "artifact_hashes"
        else "_summary_markdown"
    )
    monkeypatch.setattr(f"biofield.la1_artifacts.{target}", fail)
    with pytest.raises(LA1RunExecutionError, match="injected"):
        execute_la1_run(run_directory)

    finalization = _read_json(run_directory / "finalization.json")
    assert finalization["status"] == "failed"
    replayed = replay_la1_run(run_directory)
    assert replayed.status == "failed"
    assert set(replayed.metrics["cost_vector"]) == EXPECTED_COST_FIELDS


@pytest.mark.parametrize("failure_point", ("write_summary", "finalize"))
def test_post_metrics_failure_uses_sealed_authoritative_failure_metrics(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id=f"post-metrics-failed-{failure_point}",
        scenario="success",
    )
    original = getattr(la1_module.RunArtifactStore, failure_point)
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(f"injected post-metrics {failure_point} failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        la1_module.RunArtifactStore,
        failure_point,
        fail_once,
    )
    with pytest.raises(LA1RunExecutionError, match="injected post-metrics"):
        execute_la1_run(run_directory)

    partial_metrics = _read_json(run_directory / "metrics.json")
    assert partial_metrics["run_validity"] == "valid"
    assert "failure" not in partial_metrics
    assert (run_directory / "artifacts" / "failure_metrics.json").is_file()
    assert (run_directory / "artifacts" / "failure.json").is_file()

    finalization = _read_json(run_directory / "finalization.json")
    assert finalization["status"] == "failed"
    replayed = replay_la1_run(run_directory)
    assert replayed.status == "failed"
    assert replayed.metrics["run_validity"] == "invalid-run"
    assert replayed.metrics["failure"]["error_type"] == "RuntimeError"
    assert replayed.metrics["failure"]["excluded_from_denominator"] is False
    assert "public_terminal_hash" not in replayed.metrics
    assert set(replayed.metrics["cost_vector"]) == EXPECTED_COST_FIELDS
    assert replayed.metrics["partial_metrics"] == {
        "authoritative": False,
        "path": "metrics.json",
        "sha256": hashlib.sha256(
            (run_directory / "metrics.json").read_bytes()
        ).hexdigest(),
    }
    authoritative_summary_path = run_directory / "artifacts" / "failure_summary.json"
    assert authoritative_summary_path.is_file()
    authoritative_summary = _read_json(authoritative_summary_path)
    assert authoritative_summary == {
        "schema_version": 1,
        "authority": "authoritative",
        "scenario": "success",
        "run_validity": "invalid-run",
        "markdown": (
            "# LA1 scripted run\n\n"
            "- Scenario: `success`\n"
            "- Run validity: `invalid-run`\n"
            "- Failure: `RuntimeError`\n"
            "- Claim boundary: retained runner failure; excluded from scientific "
            "support but not silently removed from the run ledger.\n"
        ),
    }
    assert replayed.metrics["authoritative_summary"] == {
        "path": "artifacts/failure_summary.json",
        "sha256": hashlib.sha256(authoritative_summary_path.read_bytes()).hexdigest(),
    }
    if failure_point == "finalize":
        assert replayed.metrics["partial_summary"] == {
            "authoritative": False,
            "path": "summary.md",
            "sha256": hashlib.sha256(
                (run_directory / "summary.md").read_bytes()
            ).hexdigest(),
        }
    else:
        assert "partial_summary" not in replayed.metrics

    authoritative_path = run_directory / "artifacts" / "failure_metrics.json"
    authoritative = _read_json(authoritative_path)
    authoritative["failure"]["message"] = "forged late failure"
    authoritative_path.write_text(
        json.dumps(
            authoritative,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="authoritative failure metrics",
    ):
        replay_la1_run(run_directory)


def test_failed_run_rejects_unlabelled_valid_partial_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="unlabelled-valid-summary",
        scenario="success",
    )
    original_finalize = la1_module.RunArtifactStore.finalize
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected finalization failure")
        return original_finalize(*args, **kwargs)

    monkeypatch.setattr(
        la1_module.RunArtifactStore,
        "finalize",
        fail_once,
    )
    with pytest.raises(LA1RunExecutionError):
        execute_la1_run(run_directory)

    authoritative_path = run_directory / "artifacts" / "failure_metrics.json"
    authoritative = _read_json(authoritative_path)
    authoritative.pop("partial_summary")
    authoritative_path.write_text(
        json.dumps(
            authoritative,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    events = tuple(
        json.loads(line)
        for line in (run_directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    failure_payload = events[-1]["payload"]
    final_state = {
        "scenario": "success",
        "status": "failed",
        "failure_sha256": hashlib.sha256(
            json.dumps(
                failure_payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "authoritative_metrics": {
            "path": "artifacts/failure_metrics.json",
            "sha256": hashlib.sha256(authoritative_path.read_bytes()).hexdigest(),
        },
        "partial_metrics": authoritative["partial_metrics"],
        "failure_record": authoritative["failure_record"],
        "authoritative_summary": authoritative["authoritative_summary"],
        "artifact_sha256": authoritative["artifact_sha256"],
    }
    finalization_path = run_directory / "finalization.json"
    finalization = _read_json(finalization_path)
    finalization["final_state_sha256"] = hashlib.sha256(
        json.dumps(
            final_state,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    finalization_path.write_text(
        json.dumps(
            finalization,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="failed run summary",
    ):
        replay_la1_run(run_directory)


def test_source_manifest_covers_transitive_la_runtime_modules(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="source-closure-1",
        scenario="success",
    )
    source_hashes = _read_json(run_directory / "config.json")["source_sha256"]
    assert {
        "src/biofield/__init__.py",
        "src/biofield/admission.py",
        "src/biofield/artifacts.py",
        "src/biofield/commitment.py",
        "src/biofield/communication.py",
        "src/biofield/contracts.py",
        "src/biofield/dispute_runtime.py",
        "src/biofield/failure_checkpoint.py",
        "src/biofield/failure_runtime.py",
        "src/biofield/gate_episode.py",
        "src/biofield/la1_artifacts.py",
        "src/biofield/la1_governance.py",
        "src/biofield/ledger.py",
        "src/biofield/local_runtime.py",
        "src/biofield/local_state.py",
        "src/biofield/multi_admission.py",
        "src/biofield/organization.py",
        "src/biofield/refusal_runtime.py",
        "src/biofield/residual.py",
    } <= set(source_hashes)

    package_root = Path(la1_module.__file__).resolve().parent
    pending = [package_root / Path(logical_path).name for logical_path in source_hashes]
    discovered: set[str] = set()
    while pending:
        source_path = pending.pop()
        logical_path = f"src/biofield/{source_path.name}"
        if logical_path in discovered:
            continue
        discovered.add(logical_path)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            candidates: list[Path] = []
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.module:
                    candidates.append(
                        package_root / f"{node.module.rsplit('.', 1)[-1]}.py"
                    )
                else:
                    candidates.extend(
                        package_root / f"{alias.name}.py" for alias in node.names
                    )
            elif isinstance(node, ast.Import):
                candidates.extend(
                    package_root / f"{alias.name.rsplit('.', 1)[-1]}.py"
                    for alias in node.names
                    if alias.name.startswith("biofield.")
                )
            pending.extend(candidate for candidate in candidates if candidate.is_file())

    assert discovered <= set(source_hashes)


def test_source_manifest_resolves_modules_from_an_installed_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = la1_module._source_hashes()
    installed_package = tmp_path / "site-packages" / "biofield"
    installed_package.mkdir(parents=True)
    checkout_package = Path(la1_module.__file__).resolve().parent
    for logical_path in expected:
        module_name = Path(logical_path).name
        (installed_package / module_name).write_bytes(
            (checkout_package / module_name).read_bytes()
        )

    monkeypatch.setattr(
        la1_module,
        "__file__",
        str(installed_package / "la1_artifacts.py"),
    )

    assert la1_module._source_hashes() == expected


def test_replay_rejects_unsealed_or_symlink_nested_artifacts(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="nested-artifact-1",
        scenario="success",
    )
    execute_la1_run(run_directory)
    injected = run_directory / "artifacts" / "unsealed.bin"
    injected.write_bytes(b"forged")
    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="artifact file set",
    ):
        replay_la1_run(run_directory)
    injected.unlink()

    organization = run_directory / "artifacts" / "organization_snapshot.json"
    external = tmp_path / "organization-copy.json"
    external.write_bytes(organization.read_bytes())
    organization.unlink()
    os.symlink(external, organization)
    with pytest.raises(
        LA1ArtifactIntegrityError,
        match="symbolic link",
    ):
        replay_la1_run(run_directory)


def test_governance_paths_run_seals_all_missing_protocol_paths(
    tmp_path: Path,
) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="governance-paths-1",
        scenario="governance_paths",
    )
    executed = execute_la1_run(run_directory)
    assert executed.status == "completed"
    assert executed.organization_snapshot is not None
    assert executed.organization_snapshot.run_id == "governance-paths-1"
    governance = _read_json(run_directory / "artifacts" / "governance_paths.json")
    assert governance["run_id"] == "governance-paths-1"
    event_types = {event.event_type for event in executed.events}
    assert {
        "governance_rejected_feedback",
        "governance_dispute_quarantine",
        "governance_revalidation",
        "governance_resource_insufficient",
        "governance_illegal_proposal",
        "governance_terminal",
    } <= event_types
    coverage = executed.metrics["canonical_path_coverage"]
    assert coverage == {
        "disputed_quarantine_revalidation": True,
        "illegal_proposal_zero_side_effects": True,
        "rejected_feedback_no_positive_credit": True,
        "resource_insufficient_rejected": True,
    }
    assert executed.metrics["illegal_rejection"]["rate"] == 1.0
    assert executed.metrics["cost_vector"]["tool_calls"] == 3
    assert executed.metrics["cost_vector"]["verifier_calls"] == 3
    assert executed.metrics["cost_vector"]["state_update_calls"] == 2
    assert executed.metrics["state_update_provenance"]["status"] == "not_applicable"
    assert executed.metrics["native_state_update_provenance"] == {
        "numerator": 2,
        "denominator": 2,
        "rate": 1.0,
        "status": "measured",
        "trace_count": 2,
    }
    assert replay_la1_run(run_directory).metrics == executed.metrics


def test_native_state_update_provenance_fails_closed_on_source_parent_drift() -> None:
    native = dict(
        la1_module.run_governance_evidence("native-provenance-drift").artifact
    )
    rejected = [dict(event) for event in native["rejected_events"]]
    index = next(
        index
        for index, event in enumerate(rejected)
        if event["event_type"] == "local_state_update"
    )
    drifted = dict(rejected[index])
    drifted["causal_parent_ids"] = ["local-state-initial-agent-governance-v0"]
    rejected[index] = drifted
    native["rejected_events"] = rejected

    assert la1_module._native_state_update_provenance(native) == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
        "status": "measured",
        "trace_count": 2,
    }


def test_cli_prepare_run_replay_and_summarize_emit_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs"
    assert (
        main(
            [
                "prepare",
                "--output",
                str(output),
                "--run-id",
                "cli-success-1",
                "--scenario",
                "success",
            ]
        )
        == 0
    )
    prepared = json.loads(capsys.readouterr().out)
    run_directory = Path(prepared["run_directory"])
    assert prepared == {
        "run_directory": str(run_directory),
        "run_id": "cli-success-1",
        "scenario": "success",
        "status": "prepared",
    }

    assert main(["run", "--run-directory", str(run_directory)]) == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["status"] == "completed"
    assert len(executed["terminal_projection_sha256"]) == 64

    assert main(["replay", "--run-directory", str(run_directory)]) == 0
    replayed = json.loads(capsys.readouterr().out)
    assert replayed["status"] == "completed"
    assert (
        replayed["terminal_projection_sha256"]
        == (executed["terminal_projection_sha256"])
    )

    assert main(["summarize", "--run-directory", str(run_directory)]) == 0
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["schema_version"] == "la1.metrics.v2"
    assert metrics["public_terminal_hash"] == (executed["terminal_projection_sha256"])


def test_cli_errors_are_nonzero_and_never_overwrite(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    arguments = [
        "prepare",
        "--output",
        str(tmp_path / "runs"),
        "--run-id",
        "duplicate-1",
        "--scenario",
        "failure_recovery",
    ]
    assert main(arguments) == 0
    run_directory = Path(json.loads(capsys.readouterr().out)["run_directory"])

    assert main(arguments) != 0
    duplicate_error = json.loads(capsys.readouterr().err)
    assert duplicate_error["status"] == "error"
    assert duplicate_error["error_type"] == "ArtifactExistsError"

    assert main(["run", "--run-directory", str(run_directory)]) == 0
    capsys.readouterr()
    assert main(["run", "--run-directory", str(run_directory)]) != 0
    finalized_error = json.loads(capsys.readouterr().err)
    assert finalized_error["error_type"] == "RunFinalizedError"


@pytest.mark.parametrize(
    "arguments",
    (
        ("prepare",),
        ("unknown-command",),
        ("prepare", "--unknown-option"),
    ),
)
def test_cli_usage_errors_are_single_line_json_without_argparse_usage(
    arguments: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(arguments) == 2
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error["status"] == "error"
    assert error["error_type"] == "LA1CLIUsageError"
    assert "usage:" not in captured.err
    assert captured.out == ""


def test_cli_prepare_accepts_output_directory_alias(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert (
        main(
            [
                "prepare",
                "--output-directory",
                str(tmp_path / "runs"),
                "--run-id",
                "output-alias-1",
                "--scenario",
                "success",
            ]
        )
        == 0
    )
    prepared = json.loads(capsys.readouterr().out)
    assert Path(prepared["run_directory"]).is_dir()


def test_replay_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="symlink-target",
        scenario="success",
    )
    execute_la1_run(run_directory)
    alias = tmp_path / "runs" / "la1-scripted" / "symlink-alias"
    alias.symlink_to(run_directory, target_is_directory=True)

    with pytest.raises(LA1ArtifactIntegrityError, match="symbolic link|invalid"):
        replay_la1_run(alias)


def test_replay_rejects_symlinked_finalization(tmp_path: Path) -> None:
    run_directory = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="finalization-symlink",
        scenario="success",
    )
    execute_la1_run(run_directory)
    external_finalization = tmp_path / "external-finalization.json"
    external_finalization.write_bytes(
        (run_directory / "finalization.json").read_bytes()
    )
    (run_directory / "finalization.json").unlink()
    (run_directory / "finalization.json").symlink_to(external_finalization)

    with pytest.raises(LA1ArtifactIntegrityError, match="symbolic link|finalization"):
        replay_la1_run(run_directory)


def test_execute_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    target = prepare_la1_run(
        output_directory=tmp_path / "runs",
        run_id="execute-symlink-target",
        scenario="success",
    )
    alias = tmp_path / "runs" / "la1-scripted" / "execute-symlink-alias"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(LA1ArtifactIntegrityError, match="symbolic link|invalid"):
        execute_la1_run(alias)
