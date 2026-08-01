from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import biofield.e0_run as e0_run_module
from biofield.e0_run import (
    E0ArtifactExistsError,
    E0RunExecutionError,
    E0RunFinalizedError,
    E0RunIntegrityError,
    E0RunStore,
    execute_e0_run,
    main,
    prepare_e0_run,
    replay_e0_run,
    summarize_e0_run,
)
from biofield.evidence_task import load_task_bundle
from biofield.f0 import DeterministicF0Executor, F0Experiment, F0RunConfig


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _source_runs(tmp_path: Path) -> dict[str, Path]:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    settings = {
        "completed": (3, 5, None, None),
        "failed": (3, 5, "contradiction_resolution", None),
        "budget_exhausted": (1, 5, None, None),
        "max_cycles": (2, 2, None, "fact_extraction"),
    }
    runs: dict[str, Path] = {}
    for expected, (action_budget, max_cycles, fail_on, invalid_on) in settings.items():
        result = F0Experiment(
            bundle=bundle,
            executor=DeterministicF0Executor(
                bundle,
                fail_on_requirement=fail_on,
                invalid_on_requirement=invalid_on,
            ),
            config=F0RunConfig(
                output_directory=tmp_path / "source-runs",
                run_id=f"source-{expected}",
                action_budget=action_budget,
                max_cycles=max_cycles,
            ),
        ).run()
        assert result.status.value == expected
        runs[expected] = result.run_directory
    return runs


def _prepare(tmp_path: Path, sources: dict[str, Path]) -> Path:
    return prepare_e0_run(
        lock_directory=tmp_path / "locks",
        lock_id="e0-lock",
        source_run_directories=sources,
    )


def test_prepare_execute_replay_and_summarize_four_native_v2_terminal_paths(
    tmp_path: Path,
) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_seal = json.loads(
        lock_path.with_name("lock.seal.json").read_text(encoding="utf-8")
    )
    assert lock["schema_version"] == 2
    assert lock["runner_version"] == "e0.artifact-runner.v2"
    assert lock["stream_kind"] == "f0.native.v2"
    assert lock["terminal_cases"] == [
        "completed",
        "failed",
        "budget_exhausted",
        "max_cycles",
    ]
    assert set(lock["source_hashes"]) == {
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
    }
    assert lock["fixture_hashes"] == {
        "r1/cold_chain_readiness/answer_key.v1.json": (
            "a22fa9b63e016e7a9b658a0a0ff7692ede9484bcee45a6e5702d9396b31e74ae"
        ),
        "r1/cold_chain_readiness/task.v1.json": (
            "dbd38a6d77583d6ced24349f53df9672efc34a45571c21084fb12981a1fb1be9"
        ),
    }
    assert (
        lock_seal["e0_lock_sha256"]
        == hashlib.sha256(lock_path.read_bytes()).hexdigest()
    )
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="e0-matrix-1",
    )

    assert run_directory == (tmp_path / "runs" / "e0" / "e0-matrix-1").resolve()
    assert {path.name for path in run_directory.iterdir() if path.is_file()} == {
        "checkpoints.json",
        "config.json",
        "environment.json",
        "events.ndjson",
        "metrics.json",
        "preregistration.lock.json",
        "replay.json",
        "seal.json",
        "source_manifest.json",
        "summary.json",
        "terminal.json",
    }
    terminal = json.loads((run_directory / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["status"] == "completed"
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["terminal_case_count"] == 4
    assert set(metrics["terminal_cases"]) == {
        "completed",
        "failed",
        "budget_exhausted",
        "max_cycles",
    }
    assert metrics["primitive_replay_verified"] == 4
    assert metrics["evidence_feedback_verified"] == 4
    assert metrics["checkpoint_equivalent"] == 4
    assert set(metrics["cost_vector"]) == {
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
    environment = json.loads(
        (run_directory / "environment.json").read_text(encoding="utf-8")
    )
    assert environment["python_version"]
    assert environment["platform"]
    assert set(environment["dependencies"]) == {"jsonschema", "numpy"}
    assert set(environment["git"]) == {
        "available",
        "commit",
        "dirty",
        "dirty_state_sha256",
    }

    replayed = replay_e0_run(run_directory)
    assert replayed.verified is True
    assert replayed.terminal_case_count == 4
    assert replayed.checkpoint_equivalent_count == 4
    assert set(replayed.terminal_statuses) == set(metrics["terminal_cases"])
    assert len(replayed.replay_sha256) == 64

    summary = summarize_e0_run(run_directory)
    assert summary["claim_limit"] == "E0 deterministic public replay only"
    assert summary["terminal_case_count"] == 4
    assert summary["sealed"] is True

    seal = json.loads((run_directory / "seal.json").read_text(encoding="utf-8"))
    assert seal["status"] == "completed"
    assert set(seal["file_sha256"]) == {
        path.name
        for path in run_directory.iterdir()
        if path.is_file() and path.name != "seal.json"
    }


def test_locked_source_manifest_covers_transitive_local_imports(
    tmp_path: Path,
) -> None:
    lock = json.loads(_prepare(tmp_path, _source_runs(tmp_path)).read_text())
    locked = set(lock["source_hashes"])
    package = Path(e0_run_module.__file__).parent

    for source_name in locked:
        tree = ast.parse((package / source_name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            dependency: str | None = None
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                dependency = f"{node.module.split('.', 1)[0]}.py"
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.startswith("biofield.")
            ):
                dependency = f"{node.module.split('.', 2)[1]}.py"
            if dependency is not None and (package / dependency).is_file():
                assert dependency in locked, (
                    f"{source_name} imports unlocked {dependency}"
                )


def test_replay_fails_closed_when_locked_fixture_bytes_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="fixture-drift",
    )
    copied_fixture_root = tmp_path / "fixture-copy"
    shutil.copytree(FIXTURE_ROOT.parent, copied_fixture_root)
    task_path = copied_fixture_root / "r1" / "cold_chain_readiness" / "task.v1.json"
    task_path.write_bytes(task_path.read_bytes() + b"\n")
    monkeypatch.setattr(e0_run_module, "fixture_root", lambda: copied_fixture_root)

    with pytest.raises(E0RunIntegrityError, match="fixture hash"):
        replay_e0_run(run_directory)


def test_schema1_runner_v1_run_remains_backward_replayable(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="legacy-v1",
    )
    legacy_source_hashes = {
        "__init__.py": (
            "48b56c1c757983ce5eb397d74ddac6e1e38730f1c045440ed618ee6968e3bcb2"
        ),
        "artifacts.py": (
            "eb39d05b4e57cd30e6261cee370b5be71a051dff5352a9eb37653a4f0c2dee92"
        ),
        "contracts.py": (
            "8a14c84c8c3d51a8662a34ae2f250a5730c9a422c623fc47b740146b3ef630d5"
        ),
        "e0.py": "256d1c08cc27cbfe52ea17155391069bdd11b9f8dd1309c29ad936e53f6b9ba1",
        "e0_run.py": (
            "fa53744145b6088f85a8efe304f1c1e7fc0afa77f858aabceefe7a261cb868b0"
        ),
        "evidence_task.py": (
            "6767de90ebb4275555b9593af5f0a33832353dff52daedc739a7d408f8e3eb13"
        ),
        "f0.py": "d2a9801e64f9867fd0f0e83471f305eded96ca6cf1590f7beabdc2b0c1e2100d",
        "ledger.py": (
            "ac2d4d3447e0059fdc5f7d809083095a863e2442db8a8032f4ff4164c322bd6e"
        ),
        "residual.py": (
            "de0a7907c8f479942364d4372942c077f869182f8397efcac01dccec93a007fc"
        ),
        "resources.py": (
            "89399e314ef5d446853853c680f6331efeece4c257512c138625b05c7b5f8213"
        ),
    }

    copied_lock_path = run_directory / "preregistration.lock.json"
    copied_lock = json.loads(copied_lock_path.read_text(encoding="utf-8"))
    copied_lock["schema_version"] = 1
    copied_lock["runner_version"] = "e0.artifact-runner.v1"
    copied_lock["source_hashes"] = legacy_source_hashes
    copied_lock.pop("fixture_hashes")
    copied_lock_path.write_text(
        json.dumps(copied_lock, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    source_manifest_path = run_directory / "source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["source_hashes"] = legacy_source_hashes
    source_manifest.pop("fixture_hashes")
    source_manifest_path.write_text(
        json.dumps(source_manifest, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    config_path = run_directory / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["runner_version"] = "e0.artifact-runner.v1"
    config["lock_sha256"] = hashlib.sha256(copied_lock_path.read_bytes()).hexdigest()
    config_path.write_text(
        json.dumps(config, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    replay_path = run_directory / "replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay["runner_version"] = "e0.artifact-runner.v1"
    replay_path.write_text(
        json.dumps(replay, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    seal_path = run_directory / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    file_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_directory.iterdir())
        if path.is_file() and path.name != "seal.json"
    }
    seal["runner_version"] = "e0.artifact-runner.v1"
    seal["file_sha256"] = file_hashes
    seal["artifact_bundle_sha256"] = hashlib.sha256(
        json.dumps(file_hashes, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    seal_path.write_text(
        json.dumps(seal, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = replay_e0_run(run_directory)

    assert report.verified is True
    assert report.terminal_case_count == 4


def test_schema1_runner_v1_lock_is_replay_only_for_new_execution(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path, _source_runs(tmp_path))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schema_version"] = 1
    lock["runner_version"] = "e0.artifact-runner.v1"
    lock["source_hashes"] = {
        "__init__.py": (
            "48b56c1c757983ce5eb397d74ddac6e1e38730f1c045440ed618ee6968e3bcb2"
        ),
        "artifacts.py": (
            "eb39d05b4e57cd30e6261cee370b5be71a051dff5352a9eb37653a4f0c2dee92"
        ),
        "contracts.py": (
            "8a14c84c8c3d51a8662a34ae2f250a5730c9a422c623fc47b740146b3ef630d5"
        ),
        "e0.py": "256d1c08cc27cbfe52ea17155391069bdd11b9f8dd1309c29ad936e53f6b9ba1",
        "e0_run.py": (
            "fa53744145b6088f85a8efe304f1c1e7fc0afa77f858aabceefe7a261cb868b0"
        ),
        "evidence_task.py": (
            "6767de90ebb4275555b9593af5f0a33832353dff52daedc739a7d408f8e3eb13"
        ),
        "f0.py": ("d2a9801e64f9867fd0f0e83471f305eded96ca6cf1590f7beabdc2b0c1e2100d"),
        "ledger.py": (
            "ac2d4d3447e0059fdc5f7d809083095a863e2442db8a8032f4ff4164c322bd6e"
        ),
        "residual.py": (
            "de0a7907c8f479942364d4372942c077f869182f8397efcac01dccec93a007fc"
        ),
        "resources.py": (
            "89399e314ef5d446853853c680f6331efeece4c257512c138625b05c7b5f8213"
        ),
    }
    lock.pop("fixture_hashes")
    lock_path.write_text(
        json.dumps(lock, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lock_seal_path = lock_path.with_name("lock.seal.json")
    lock_seal = json.loads(lock_seal_path.read_text(encoding="utf-8"))
    lock_seal["e0_lock_sha256"] = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    lock_seal_path.write_text(
        json.dumps(lock_seal, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(E0RunIntegrityError, match="replay-only"):
        execute_e0_run(
            lock_path=lock_path,
            output_directory=tmp_path / "new-runs",
            run_id="must-not-start",
        )

    assert not (tmp_path / "new-runs" / "e0" / "must-not-start").exists()


def test_prepare_run_ids_and_finalized_store_are_write_once(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    with pytest.raises(E0ArtifactExistsError, match="lock.*exists"):
        _prepare(tmp_path, sources)

    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="write-once",
    )
    with pytest.raises(E0ArtifactExistsError, match="run.*exists"):
        execute_e0_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="write-once",
        )
    store = E0RunStore.open(run_directory)
    with pytest.raises(E0RunFinalizedError, match="finalized"):
        store.write_json("late.json", {"late": True})


def test_tampered_run_or_lock_fails_closed(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="tamper-target",
    )
    events_path = run_directory / "events.ndjson"
    event_lines = events_path.read_text(encoding="utf-8").splitlines()
    first_event = json.loads(event_lines[0])
    first_event["public_event"]["payload"]["run_id"] = "forged-source-run"
    event_lines[0] = json.dumps(
        first_event,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    events_path.write_text("\n".join(event_lines) + "\n", encoding="utf-8")

    with pytest.raises(E0RunIntegrityError, match="hash mismatch"):
        replay_e0_run(run_directory)
    with pytest.raises(E0RunIntegrityError, match="hash mismatch"):
        summarize_e0_run(run_directory)

    # Recomputing the unkeyed outer seal is insufficient: replay still binds
    # the event bundle to the independently prepared source-run lock.
    seal_path = run_directory / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["file_sha256"]["events.ndjson"] = hashlib.sha256(
        events_path.read_bytes()
    ).hexdigest()
    seal["artifact_bundle_sha256"] = hashlib.sha256(
        json.dumps(
            seal["file_sha256"],
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    seal_path.write_text(
        json.dumps(
            seal,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(E0RunIntegrityError, match="event bundle differs"):
        replay_e0_run(run_directory)

    second_lock = prepare_e0_run(
        lock_directory=tmp_path / "locks",
        lock_id="tampered-lock",
        source_run_directories=sources,
    )
    second_lock.write_text("{}", encoding="utf-8")
    with pytest.raises(E0RunIntegrityError, match="lock.*hash"):
        execute_e0_run(
            lock_path=second_lock,
            output_directory=tmp_path / "runs",
            run_id="bad-lock",
        )


def test_source_tamper_preserves_a_sealed_machine_readable_failed_run(
    tmp_path: Path,
) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    source_events = sources["completed"] / "events.jsonl"
    source_events.write_bytes(source_events.read_bytes() + b"\n")

    with pytest.raises(E0RunExecutionError) as caught:
        execute_e0_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="failed-source",
        )

    run_directory = caught.value.run_directory
    assert run_directory.is_dir()
    failure = json.loads((run_directory / "failure.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8"))
    terminal = json.loads((run_directory / "terminal.json").read_text(encoding="utf-8"))
    seal = json.loads((run_directory / "seal.json").read_text(encoding="utf-8"))
    assert failure["error_type"]
    assert failure["message"]
    assert terminal["status"] == "failed"
    assert seal["status"] == "failed"
    assert "failure.json" in seal["file_sha256"]
    assert set(metrics["cost_vector"]) == {
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
    assert metrics["cost_vector"]["wall_time_ms"] >= 1
    assert metrics["cost_vector"]["cpu_time_ms"] >= 1
    assert {
        name: value
        for name, value in metrics["cost_vector"].items()
        if name not in {"wall_time_ms", "cpu_time_ms"}
    } == {
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
        "bytes_transferred": 0,
        "communication_messages": 0,
        "communication_tokens": 0,
        "state_update_calls": 0,
        "verifier_calls": 0,
        "deterministic_check_calls": 0,
        "judge_calls": 0,
        "human_escalations": 0,
        "retry_count": 0,
    }
    assert metrics["cost_vector_accounting"] == {
        "basis": "partial_run_until_failure",
        "elapsed_fields": ["wall_time_ms", "cpu_time_ms"],
        "zero_fields": [
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
        ],
    }
    with pytest.raises(E0RunIntegrityError, match="completed"):
        replay_e0_run(run_directory)


def test_argparse_cli_runs_sources_prepare_run_replay_and_summarize_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "sources",
                "--output-directory",
                str(tmp_path / "source-runs"),
                "--source-set-id",
                "cli-source",
            ]
        )
        == 0
    )
    sources_output = json.loads(capsys.readouterr().out)
    assert sources_output["command"] == "sources"
    assert set(sources_output["source_run_directories"]) == {
        "completed",
        "failed",
        "budget_exhausted",
        "max_cycles",
    }

    source_paths = sources_output["source_run_directories"]
    prepare_args = [
        "prepare",
        "--lock-directory",
        str(tmp_path / "locks"),
        "--lock-id",
        "cli-lock",
    ]
    for status in ("completed", "failed", "budget_exhausted", "max_cycles"):
        prepare_args.extend([f"--{status.replace('_', '-')}", source_paths[status]])
    assert main(prepare_args) == 0
    prepare_output = json.loads(capsys.readouterr().out)
    assert prepare_output["command"] == "prepare"
    lock_path = prepare_output["lock_path"]

    assert (
        main(
            [
                "run",
                "--lock",
                lock_path,
                "--output-directory",
                str(tmp_path / "runs"),
                "--run-id",
                "cli-run",
            ]
        )
        == 0
    )
    run_output = json.loads(capsys.readouterr().out)
    assert run_output["command"] == "run"
    run_directory = run_output["run_directory"]

    assert main(["replay", "--run", run_directory]) == 0
    replay_output = json.loads(capsys.readouterr().out)
    assert replay_output["command"] == "replay"
    assert replay_output["report"]["verified"] is True
    assert replay_output["report"]["terminal_case_count"] == 4

    assert main(["summarize", "--run", run_directory]) == 0
    summary_output = json.loads(capsys.readouterr().out)
    assert summary_output["command"] == "summarize"
    assert summary_output["summary"]["sealed"] is True

    assert (
        main(
            [
                "run",
                "--lock",
                lock_path,
                "--output-directory",
                str(tmp_path / "runs"),
                "--run-id",
                "cli-run",
            ]
        )
        == 1
    )
    error_output = json.loads(capsys.readouterr().err)
    assert error_output["command"] == "run"
    assert error_output["error_type"] == "E0ArtifactExistsError"
    assert error_output["message"]


def test_argparse_cli_parse_errors_are_machine_readable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prepare", "--lock-id", "missing-required-arguments"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["command"] == "prepare"
    assert error["error_type"] == "argument_error"
    assert "required" in error["message"]


def test_git_snapshot_times_out_to_unavailable_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def time_out(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(e0_run_module.subprocess, "run", time_out)
    e0_run_module._git_snapshot.cache_clear()

    unavailable = {
        "available": False,
        "commit": None,
        "dirty": None,
        "dirty_state_sha256": None,
    }
    assert e0_run_module._git_snapshot() == unavailable
    assert e0_run_module._git_snapshot() == unavailable
    assert calls == [
        {
            "cwd": Path(e0_run_module.__file__).resolve().parents[2],
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": 5,
        }
    ]
    e0_run_module._git_snapshot.cache_clear()


def test_replay_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="symlink-target",
    )
    alias = tmp_path / "runs" / "e0" / "symlink-alias"
    alias.symlink_to(run_directory, target_is_directory=True)

    with pytest.raises(E0RunIntegrityError, match="symbolic link|invalid"):
        replay_e0_run(alias)


def test_replay_rejects_symlinked_seal(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    run_directory = execute_e0_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="seal-symlink",
    )
    external_seal = tmp_path / "external-seal.json"
    external_seal.write_bytes((run_directory / "seal.json").read_bytes())
    (run_directory / "seal.json").unlink()
    (run_directory / "seal.json").symlink_to(external_seal)

    with pytest.raises(E0RunIntegrityError, match="symbolic link|seal"):
        replay_e0_run(run_directory)


def test_execute_rejects_symlinked_lock(tmp_path: Path) -> None:
    sources = _source_runs(tmp_path)
    lock_path = _prepare(tmp_path, sources)
    external_directory = tmp_path / "external-lock"
    external_directory.mkdir()
    external_lock = external_directory / "e0.lock.json"
    external_lock.write_bytes(lock_path.read_bytes())
    (external_directory / "lock.seal.json").write_bytes(
        lock_path.with_name("lock.seal.json").read_bytes()
    )
    lock_path.unlink()
    lock_path.symlink_to(external_lock)

    with pytest.raises(E0RunIntegrityError, match="symbolic link|lock"):
        execute_e0_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="lock-symlink",
        )
