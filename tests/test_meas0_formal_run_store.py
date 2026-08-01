from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from biofield.meas0_formal_outcomes import seal_formal_outcome_evidence
from biofield.meas0_formal_run_store import (
    FormalRunPackageExistsError,
    FormalRunPackageIntegrityError,
    FormalRunPackageStore,
    FormalShellBackend,
    FormalShellExecution,
    run_formal_shell_lifecycle,
)
from test_meas0_formal_outcomes import _build_formal_fixture, _digest


@pytest.fixture(scope="module")
def formal_fixture(tmp_path_factory: pytest.TempPathFactory):
    plan, run, manifest, package = _build_formal_fixture(tmp_path_factory)
    evidence = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=_digest("formal-shell-source-lock"),
    )
    return plan, run, manifest, package, evidence


def _read_kwargs(formal_fixture) -> dict[str, object]:
    plan, run, manifest, package, evidence = formal_fixture
    return {
        "plan": plan,
        "run": run,
        "outcome_evidence": evidence,
        "oracle_manifest": manifest,
        "outcomes": package.outcomes,
    }


def test_store_publishes_exact_lifecycle_and_replays_from_sealed_bytes(
    tmp_path: Path,
    formal_fixture,
) -> None:
    plan, run, _, _, evidence = formal_fixture
    package_directory = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="formal-shell-evidence",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    relative_files = {
        path.relative_to(package_directory).as_posix()
        for path in package_directory.rglob("*")
        if path.is_file()
    }
    assert relative_files == {
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
        "seal.json",
    }

    snapshot = FormalRunPackageStore.read(
        package_directory,
        **_read_kwargs(formal_fixture),
    )
    replay = FormalRunPackageStore.replay(
        package_directory,
        **_read_kwargs(formal_fixture),
    )
    summary = FormalRunPackageStore.summarize(
        package_directory,
        **_read_kwargs(formal_fixture),
    )
    assert snapshot.run_hash == run.run_hash
    assert snapshot.plan_hash == plan.plan_hash
    assert snapshot.outcome_bundle_hash == evidence.bundle_hash
    assert replay.verified is True
    assert replay.file_count == len(relative_files) - 1
    assert summary.case_count == 36
    assert summary.arm_case_count == 180
    assert summary.test_only is True
    assert summary.formal_eligible is False


def test_store_rejects_overwrite_and_symlinked_paths(
    tmp_path: Path,
    formal_fixture,
) -> None:
    plan, run, _, _, evidence = formal_fixture
    kwargs = {
        "package_id": "write-once",
        "plan": plan,
        "run": run,
        "outcome_evidence": evidence,
    }
    FormalRunPackageStore.publish(output_directory=tmp_path, **kwargs)
    with pytest.raises(FormalRunPackageExistsError, match="exists"):
        FormalRunPackageStore.publish(output_directory=tmp_path, **kwargs)

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(FormalRunPackageIntegrityError, match="symbolic link"):
        FormalRunPackageStore.publish(
            output_directory=linked,
            package_id="linked",
            plan=plan,
            run=run,
            outcome_evidence=evidence,
        )

    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "target"
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FormalRunPackageIntegrityError, match="symbolic link"):
        FormalRunPackageStore.read(target, **_read_kwargs(formal_fixture))

    original = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="original-name",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    renamed = original.with_name("renamed")
    original.rename(renamed)
    with pytest.raises(FormalRunPackageIntegrityError, match="directory identity"):
        FormalRunPackageStore.read(renamed, **_read_kwargs(formal_fixture))


def test_read_replay_and_summary_fail_on_missing_tamper_or_partial_publication(
    tmp_path: Path,
    formal_fixture,
) -> None:
    plan, run, _, _, evidence = formal_fixture
    package_directory = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="tamper",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    artifact_path = package_directory / "artifacts" / "000.json"
    artifact_path.write_bytes(
        artifact_path.read_bytes().replace(
            b'"execution_index":0',
            b'"execution_index":9',
        )
    )
    for operation in (
        FormalRunPackageStore.read,
        FormalRunPackageStore.replay,
        FormalRunPackageStore.summarize,
    ):
        with pytest.raises(FormalRunPackageIntegrityError, match="hash|artifact"):
            operation(package_directory, **_read_kwargs(formal_fixture))

    missing_directory = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="missing",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    (missing_directory / "summary.json").unlink()
    with pytest.raises(FormalRunPackageIntegrityError, match="file set|missing"):
        FormalRunPackageStore.read(
            missing_directory,
            **_read_kwargs(formal_fixture),
        )

    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FormalRunPackageIntegrityError, match="seal|partial"):
        FormalRunPackageStore.read(partial, **_read_kwargs(formal_fixture))

    resealed = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="resealed",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    config_path = resealed / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["formal_eligible"] = True
    config_path.write_text(
        json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    seal_path = resealed / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    from biofield import meas0_formal_run_store as store_module

    seal["file_sha256"]["config.json"] = store_module._file_hash(config_path)
    seal["package_hash"] = store_module._manifest_hash(seal["file_sha256"])
    seal_path.write_text(
        json.dumps(seal, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(FormalRunPackageIntegrityError, match="typed ancestry"):
        FormalRunPackageStore.read(resealed, **_read_kwargs(formal_fixture))

    linked_artifact = FormalRunPackageStore.publish(
        output_directory=tmp_path,
        package_id="linked-artifact",
        plan=plan,
        run=run,
        outcome_evidence=evidence,
    )
    summary_path = linked_artifact / "summary.json"
    summary_copy = tmp_path / "summary-copy.json"
    summary_copy.write_bytes(summary_path.read_bytes())
    summary_path.unlink()
    summary_path.symlink_to(summary_copy)
    with pytest.raises(FormalRunPackageIntegrityError, match="symbolic link"):
        FormalRunPackageStore.read(
            linked_artifact,
            **_read_kwargs(formal_fixture),
        )


def test_interrupted_publish_leaves_a_fail_closed_write_once_partial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    formal_fixture,
) -> None:
    plan, run, _, _, evidence = formal_fixture
    from biofield import meas0_formal_run_store as store_module

    original = store_module._atomic_write_json
    calls = 0

    def interrupt(path, value):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected partial publication")
        return original(path, value)

    monkeypatch.setattr(store_module, "_atomic_write_json", interrupt)
    with pytest.raises(FormalRunPackageIntegrityError, match="publish"):
        FormalRunPackageStore.publish(
            output_directory=tmp_path,
            package_id="interrupted",
            plan=plan,
            run=run,
            outcome_evidence=evidence,
        )
    partial = tmp_path / "interrupted"
    assert partial.is_dir()
    assert not (partial / "seal.json").exists()
    with pytest.raises(FormalRunPackageIntegrityError, match="seal|partial"):
        FormalRunPackageStore.read(partial, **_read_kwargs(formal_fixture))
    with pytest.raises(FormalRunPackageExistsError, match="exists"):
        FormalRunPackageStore.publish(
            output_directory=tmp_path,
            package_id="interrupted",
            plan=plan,
            run=run,
            outcome_evidence=evidence,
        )


def test_injectable_python_backend_has_no_readiness_bypass_flag(
    tmp_path: Path,
    formal_fixture,
) -> None:
    plan, run, _, _, evidence = formal_fixture

    class Backend:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, received_plan):
            self.calls += 1
            assert received_plan is plan
            return FormalShellExecution(
                run=run,
                outcome_evidence=evidence,
            )

    backend = Backend()
    assert isinstance(backend, FormalShellBackend)
    parameters = inspect.signature(run_formal_shell_lifecycle).parameters
    assert "fake" not in parameters
    assert "skip_readiness" not in parameters

    package_directory = run_formal_shell_lifecycle(
        plan=plan,
        backend=backend,
        output_directory=tmp_path,
        package_id="backend-run",
    )
    assert backend.calls == 1
    assert (
        json.loads((package_directory / "config.json").read_text(encoding="utf-8"))[
            "formal_eligible"
        ]
        is False
    )
