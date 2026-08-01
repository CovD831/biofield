from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path

import pytest
import biofield.meas0_pilot_run as pilot_run_module

from biofield.meas0_pilot_run import (
    FOUNDATION_CLAIM_LIMIT,
    FORMAL_CLAIM_LIMIT,
    PilotExecutionMode,
    PilotRunArtifactExistsError,
    PilotRunFinalizedError,
    PilotRunIntegrityError,
    PilotRunReadinessError,
    PilotRunStore,
    execute_pilot_run,
    prepare_pilot_run,
    replay_pilot_run,
    summarize_pilot_run,
)
from biofield.meas0_readiness import (
    FormalArtifactLayout,
    FormalReadinessBundle,
    FormalReadinessInputs,
    FormalReadinessValidator,
    arm_order_manifest,
)


DESIGN_DOCUMENT = (
    Path(__file__).parents[1] / "docs" / "experiments" / "MEAS0_DESIGN_V1.md"
)


def _prepare(tmp_path: Path, lock_id: str = "pilot-lock") -> Path:
    return prepare_pilot_run(
        lock_directory=tmp_path / "locks",
        lock_id=lock_id,
        design_document=DESIGN_DOCUMENT,
    )


def _rewrite_and_reseal_lock(lock_path: Path, lock: dict[str, object]) -> None:
    encoded = (
        json.dumps(
            lock,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    lock_path.write_text(encoded, encoding="utf-8")
    seal_path = lock_path.with_name("lock.seal.json")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["preregistration_lock_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
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


def _rewrite_run_json_and_reseal(
    run_directory: Path,
    relative_path: str,
    value: dict[str, object],
) -> None:
    content = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    (run_directory / relative_path).write_bytes(content)
    seal_path = run_directory / "seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["file_sha256"][relative_path] = hashlib.sha256(content).hexdigest()
    payload = b"".join(
        path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n"
        for path, digest in sorted(seal["file_sha256"].items())
    )
    seal["artifact_bundle_hash"] = hashlib.sha256(payload).hexdigest()
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


def test_prepare_writes_frozen_write_once_preregistration_lock(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_seal = json.loads(
        lock_path.with_name("lock.seal.json").read_text(encoding="utf-8")
    )

    assert lock["schema_version"] == 2
    assert lock["phase"] == "pilot"
    assert lock["claim_limit"] == FOUNDATION_CLAIM_LIMIT
    binding = lock["design_binding"]
    assert binding["schema_version"] == 1
    assert binding["kind"] == "embedded_bytes_base64"
    assert binding["source_name"] == DESIGN_DOCUMENT.name
    assert binding["byte_count"] == len(DESIGN_DOCUMENT.read_bytes())
    assert binding["sha256"] == lock["design_document_sha256"]
    assert (
        base64.b64decode(binding["content_base64"], validate=True)
        == DESIGN_DOCUMENT.read_bytes()
    )
    assert "design_document" not in lock
    assert lock_seal["schema_version"] == 1
    assert lock["case_count"] == 36
    assert lock["arm_case_count"] == 180
    assert lock["mutation_seed"] == 1729
    assert lock["arm_order_manifest"] == arm_order_manifest().to_dict()
    assert len(lock["case_manifest"]) == 36
    assert len(lock["native_measurement_plan_hashes"]) == 36
    assert all(
        len(value) == 64 for value in lock["native_measurement_plan_hashes"].values()
    )
    assert (
        sum(
            item["native_measurement_plan_hash"] is not None
            for item in lock["case_manifest"]
        )
        == 36
    )
    assert set(lock["source_hashes"]) == {
        "__init__.py",
        "artifacts.py",
        "contracts.py",
        "evidence_task.py",
        "meas0.py",
        "meas0_budget.py",
        "meas0_channel_order.py",
        "meas0_detection_oracle.py",
        "meas0_fixtures.py",
        "meas0_formal.py",
        "meas0_formal_derivation.py",
        "meas0_formal_lifecycle.py",
        "meas0_formal_metrics.py",
        "meas0_formal_outcomes.py",
        "meas0_formal_run_store.py",
        "meas0_formal_runner.py",
        "meas0_human.py",
        "meas0_judge_probes.py",
        "meas0_pilot_run.py",
        "meas0_pilot_runner.py",
        "meas0_preflight.py",
        "meas0_protected_artifacts.py",
        "meas0_providers.py",
        "meas0_readiness.py",
        "meas0_r1.py",
        "meas0_stage_cost.py",
        "meas0_trust.py",
        "measurement.py",
        "resources.py",
    }
    assert set(lock["evaluator_hashes"]) == {
        "cold_chain_readiness@1",
        "channel_order_ingest@1",
        "pilot_foundation@1",
    }
    assert lock_seal["preregistration_lock_sha256"]
    assert not list(lock_path.parent.glob(".*.tmp"))

    with pytest.raises(PilotRunArtifactExistsError, match="already exists"):
        _prepare(tmp_path)


def test_locked_source_manifest_covers_transitive_local_imports(
    tmp_path: Path,
) -> None:
    lock = json.loads(_prepare(tmp_path).read_text(encoding="utf-8"))
    locked = set(lock["source_hashes"])
    package = Path(pilot_run_module.__file__).parent

    for source_name in locked:
        tree = ast.parse((package / source_name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                dependency = f"{node.module.split('.', 1)[0]}.py"
                if (package / dependency).is_file():
                    assert dependency in locked, (
                        f"{source_name} imports unlocked {dependency}"
                    )


def test_v2_lock_and_run_relocate_with_embedded_design_bytes(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    relocated_lock_directory = tmp_path / "relocated" / "lock"
    relocated_lock_directory.parent.mkdir()
    lock_path.parent.rename(relocated_lock_directory)
    relocated_lock = relocated_lock_directory / lock_path.name

    run_directory = execute_pilot_run(
        lock_path=relocated_lock,
        output_directory=tmp_path / "runs",
        run_id="portable-foundation",
    )
    copied_lock = json.loads(
        (run_directory / "preregistration.lock.json").read_text(encoding="utf-8")
    )
    assert (
        base64.b64decode(
            copied_lock["design_binding"]["content_base64"],
            validate=True,
        )
        == DESIGN_DOCUMENT.read_bytes()
    )
    before_move = replay_pilot_run(run_directory)

    relocated_run = tmp_path / "relocated-run"
    run_directory.rename(relocated_run)
    after_move = replay_pilot_run(relocated_run)
    assert after_move == before_move
    assert after_move.verified is True
    assert after_move.replayed_result_count == 180


def test_v2_execution_does_not_depend_on_original_design_path(
    tmp_path: Path,
) -> None:
    design_copy = tmp_path / "temporary-design.md"
    design_copy.write_bytes(DESIGN_DOCUMENT.read_bytes())
    lock_path = prepare_pilot_run(
        lock_directory=tmp_path / "locks",
        lock_id="embedded-design",
        design_document=design_copy,
    )
    design_copy.unlink()

    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="source-deleted",
    )
    assert replay_pilot_run(run_directory).verified is True


def test_lock_is_verified_parsed_and_copied_from_one_byte_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = _prepare(tmp_path)
    original = lock_path.read_bytes()
    swapped = json.loads(original)
    swapped["lock_id"] = "swapped-after-hash"
    swapped_bytes = (
        json.dumps(
            swapped,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    real_read_bytes = Path.read_bytes
    lock_reads = 0

    def swapping_read_bytes(path: Path) -> bytes:
        nonlocal lock_reads
        if path == lock_path:
            lock_reads += 1
            return original if lock_reads == 1 else swapped_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", swapping_read_bytes)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="single-lock-snapshot",
    )

    assert lock_reads == 1
    assert (run_directory / "preregistration.lock.json").read_bytes() == original


def test_v2_requires_canonical_base64_representation(
    tmp_path: Path,
) -> None:
    design = tmp_path / "one-byte-design.md"
    design.write_bytes(b"f")
    lock_path = prepare_pilot_run(
        lock_directory=tmp_path / "locks",
        lock_id="noncanonical-base64",
        design_document=design,
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["design_binding"]["content_base64"] == "Zg=="
    lock["design_binding"]["content_base64"] = "Zh=="
    _rewrite_and_reseal_lock(lock_path, lock)

    with pytest.raises(PilotRunIntegrityError, match="design binding"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="noncanonical-base64",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "inner_hash",
        "top_hash",
        "byte_count",
        "kind",
        "missing_field",
        "extra_field",
        "valid_base64_wrong_bytes",
    ],
)
def test_v2_design_binding_contract_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    binding = lock["design_binding"]
    if mutation == "inner_hash":
        binding["sha256"] = "0" * 64
    elif mutation == "top_hash":
        lock["design_document_sha256"] = "0" * 64
    elif mutation == "byte_count":
        binding["byte_count"] += 1
    elif mutation == "kind":
        binding["kind"] = "hash_only"
    elif mutation == "missing_field":
        del binding["source_name"]
    elif mutation == "extra_field":
        binding["source_path"] = str(DESIGN_DOCUMENT.resolve())
    else:
        original = base64.b64decode(binding["content_base64"], validate=True)
        binding["content_base64"] = base64.b64encode(b"!" + original[1:]).decode(
            "ascii"
        )
    _rewrite_and_reseal_lock(lock_path, lock)

    with pytest.raises(
        PilotRunIntegrityError,
        match="design (binding|document hash)",
    ):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id=f"binding-{mutation}",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / f"binding-{mutation}").exists()


def test_v2_design_binding_tampering_and_mixed_schema_fail_before_run_creation(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["design_binding"]["content_base64"] = "***not-base64***"
    encoded = (
        json.dumps(
            lock,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    lock_path.write_text(encoded, encoding="utf-8")
    seal_path = lock_path.with_name("lock.seal.json")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["preregistration_lock_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
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

    with pytest.raises(PilotRunIntegrityError, match="design binding"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="tampered-design",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / "tampered-design").exists()

    second_lock = _prepare(tmp_path, lock_id="mixed-design-lock")
    second = json.loads(second_lock.read_text(encoding="utf-8"))
    second["design_document"] = str(DESIGN_DOCUMENT.resolve())
    second_encoded = (
        json.dumps(
            second,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    second_lock.write_text(second_encoded, encoding="utf-8")
    second_seal_path = second_lock.with_name("lock.seal.json")
    second_seal = json.loads(second_seal_path.read_text(encoding="utf-8"))
    second_seal["preregistration_lock_sha256"] = hashlib.sha256(
        second_encoded.encode("utf-8")
    ).hexdigest()
    second_seal_path.write_text(
        json.dumps(
            second_seal,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PilotRunIntegrityError, match="mixed design binding"):
        execute_pilot_run(
            lock_path=second_lock,
            output_directory=tmp_path / "runs",
            run_id="mixed-design",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / "mixed-design").exists()


@pytest.mark.parametrize("schema_version", [0, 3, True, "2"])
def test_unknown_or_non_integer_lock_schema_fails_closed(
    tmp_path: Path,
    schema_version: object,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schema_version"] = schema_version
    encoded = (
        json.dumps(
            lock,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    lock_path.write_text(encoded, encoding="utf-8")
    seal_path = lock_path.with_name("lock.seal.json")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["preregistration_lock_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
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

    with pytest.raises(PilotRunIntegrityError, match="lock schema"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="unknown-schema",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / "unknown-schema").exists()


def test_schema_v1_lock_keeps_legacy_absolute_design_verification(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schema_version"] = 1
    lock["design_document"] = str(DESIGN_DOCUMENT.resolve())
    del lock["design_binding"]
    encoded = (
        json.dumps(
            lock,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    lock_path.write_text(encoded, encoding="utf-8")
    seal_path = lock_path.with_name("lock.seal.json")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["preregistration_lock_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
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

    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="legacy-v1",
    )
    assert replay_pilot_run(run_directory).verified is True


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_schema_v1_keeps_external_design_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    legacy_design = tmp_path / "legacy-design.md"
    legacy_design.write_bytes(DESIGN_DOCUMENT.read_bytes())
    lock_path = prepare_pilot_run(
        lock_directory=tmp_path / "locks",
        lock_id=f"legacy-{mutation}",
        design_document=legacy_design,
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schema_version"] = 1
    lock["design_document"] = str(legacy_design.resolve())
    del lock["design_binding"]
    _rewrite_and_reseal_lock(lock_path, lock)
    if mutation == "missing":
        legacy_design.unlink()
    else:
        legacy_design.write_bytes(b"changed")

    with pytest.raises(PilotRunIntegrityError, match="design document hash"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id=f"legacy-{mutation}",
        )


def test_schema_v1_rejects_embedded_fallback_and_relative_path(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schema_version"] = 1
    lock["design_document"] = "relative-design.md"
    _rewrite_and_reseal_lock(lock_path, lock)

    with pytest.raises(PilotRunIntegrityError, match="mixed design binding"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="legacy-mixed",
        )

    del lock["design_binding"]
    _rewrite_and_reseal_lock(lock_path, lock)
    with pytest.raises(PilotRunIntegrityError, match="absolute"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="legacy-relative",
        )


def test_execute_persists_all_cases_arms_and_finalizes_write_once(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="foundation-1",
    )

    assert (
        run_directory
        == (tmp_path / "runs" / "meas0" / "pilot" / "foundation-1").resolve()
    )
    assert len(list((run_directory / "episode" / "cases").glob("*.json"))) == 36
    assert len(list((run_directory / "arms").glob("*/results/*.json"))) == 180
    assert (run_directory / "preregistration.lock.json").is_file()
    assert (run_directory / "case_manifest.json").is_file()
    assert (run_directory / "source_manifest.json").is_file()
    assert (run_directory / "environment.json").is_file()
    assert (run_directory / "arm_order_manifest.json").is_file()
    assert (run_directory / "events.ndjson").is_file()
    assert (run_directory / "metrics.json").is_file()
    assert (run_directory / "summary.json").is_file()
    assert (run_directory / "seal.json").is_file()
    assert not (run_directory / "gold").exists()
    assert not list(run_directory.rglob(".*.tmp"))
    first_case = "pilot.cold_chain_readiness.F01.seed1729"
    for component in (
        "task_frame.json",
        "goal_graph.json",
        "requirement_graph.json",
        "measurement_graph.json",
        "acceptance_rule.json",
    ):
        assert (
            run_directory / "task_bundle" / "cold_chain_readiness" / component
        ).is_file()
    for artifact in (
        "events.ndjson",
        "artifacts.json",
        "state_before.json",
        "state_after.json",
    ):
        assert (run_directory / "episode" / "cases" / first_case / artifact).is_file()
    for artifact in (
        "observations.ndjson",
        "evaluation_result.json",
        "cost_vector.json",
        "stderr.log",
        "budget.json",
    ):
        assert (
            run_directory / "arms" / "state_only" / "cases" / first_case / artifact
        ).is_file()

    events = [
        json.loads(line)
        for line in (run_directory / "events.ndjson").read_text().splitlines()
    ]
    first_case_arms = [
        event["arm"] for event in events if event["case_id"] == first_case
    ]
    assert first_case_arms == list(arm_order_manifest().resolved_arm_order)

    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["arm_case_count"] == 180
    assert all(item["cases"] == 36 for item in metrics["arms"].values())
    judge_results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (run_directory / "arms" / "judge_only" / "results").glob("*.json")
    ]
    assert len(judge_results) == 36
    assert all(item["unavailable"] for item in judge_results)
    assert all(item["automatic_status"] == "unknown" for item in judge_results)
    assert all(item["cost_vector"]["judge_calls"] == 0 for item in judge_results)

    store = PilotRunStore.open(run_directory)
    with pytest.raises(PilotRunFinalizedError, match="finalized"):
        store.write_json("late.json", {"late": True})
    with pytest.raises(PilotRunArtifactExistsError, match="already exists"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="foundation-1",
        )


def test_replay_verifies_seal_and_all_180_deterministic_results(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="foundation-replay",
    )

    first = replay_pilot_run(run_directory)
    second = replay_pilot_run(run_directory)

    assert first == second
    assert first.verified is True
    assert first.case_count == 36
    assert first.arm_result_count == 180
    assert first.replayed_result_count == 180
    assert len(first.replay_hash) == 64

    summary = summarize_pilot_run(run_directory)
    assert summary["claim_limit"] == FOUNDATION_CLAIM_LIMIT
    assert summary["case_count"] == 36
    assert summary["arm_case_count"] == 180
    assert summary["sealed"] is True


def test_run_and_lock_tampering_fail_closed(tmp_path: Path) -> None:
    lock_path = _prepare(tmp_path)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="tamper-target",
    )
    result_path = next(
        (run_directory / "arms" / "evaluation_plane" / "results").glob("*.json")
    )
    result_path.write_text('{"automatic_status":"pass"}', encoding="utf-8")

    with pytest.raises(PilotRunIntegrityError, match="hash mismatch"):
        replay_pilot_run(run_directory)
    with pytest.raises(PilotRunIntegrityError, match="hash mismatch"):
        summarize_pilot_run(run_directory)

    second_lock = _prepare(tmp_path, lock_id="tampered-lock")
    second_lock.write_text("{}", encoding="utf-8")
    with pytest.raises(PilotRunIntegrityError, match="lock.*hash"):
        execute_pilot_run(
            lock_path=second_lock,
            output_directory=tmp_path / "runs",
            run_id="must-not-start",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / "must-not-start").exists()


def test_arm_order_alias_is_rejected_before_run_creation(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["arms"] = list(reversed(lock["arms"]))
    encoded = (
        json.dumps(
            lock,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    lock_path.write_text(encoded, encoding="utf-8")
    seal_path = lock_path.with_name("lock.seal.json")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["preregistration_lock_sha256"] = hashlib.sha256(
        encoded.encode("utf-8")
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

    with pytest.raises(PilotRunIntegrityError, match="arm order"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="arm-order-alias",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot" / "arm-order-alias").exists()


def test_unsealed_extra_file_is_detected(tmp_path: Path) -> None:
    lock_path = _prepare(tmp_path)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="extra-file",
    )
    (run_directory / "unsealed.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PilotRunIntegrityError, match="file set"):
        replay_pilot_run(run_directory)


def test_replay_rejects_resealed_source_manifest_drift(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    run_directory = execute_pilot_run(
        lock_path=lock_path,
        output_directory=tmp_path / "runs",
        run_id="source-manifest-drift",
    )
    source_manifest_path = run_directory / "source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["source_hashes"]["meas0.py"] = "0" * 64
    _rewrite_run_json_and_reseal(
        run_directory,
        "source_manifest.json",
        source_manifest,
    )

    with pytest.raises(
        PilotRunIntegrityError,
        match="source manifest",
    ):
        replay_pilot_run(run_directory)


def test_runner_exception_leaves_a_sealed_failed_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)

    def fail_after_cases(_cases: object, **_kwargs: object) -> object:
        raise RuntimeError("injected deterministic runner failure")

    monkeypatch.setattr(
        "biofield.meas0_pilot_run.run_pilot_foundation",
        fail_after_cases,
    )
    with pytest.raises(RuntimeError, match="injected"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="failed-but-retained",
        )

    run_directory = tmp_path / "runs" / "meas0" / "pilot" / "failed-but-retained"
    seal = json.loads((run_directory / "seal.json").read_text(encoding="utf-8"))
    failure = json.loads((run_directory / "failure.json").read_text(encoding="utf-8"))
    assert seal["status"] == "failed"
    assert failure["arm_results_persisted"] == 0
    assert failure["error_type"] == "RuntimeError"
    with pytest.raises(PilotRunFinalizedError):
        PilotRunStore.open(run_directory).write_json("late.json", {})


def test_formal_mode_rejects_unready_report_before_creating_run(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    inputs = FormalReadinessInputs()
    report = FormalReadinessValidator().validate(inputs)
    bundle = FormalReadinessBundle.create(inputs)
    assert bundle.report == report
    bundle_path = tmp_path / "readiness.json"
    bundle_path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")

    with pytest.raises(PilotRunReadinessError, match="not runnable"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="formal-must-not-start",
            execution_mode=PilotExecutionMode.FORMAL,
            readiness_bundle_path=bundle_path,
            comparison_block_id="formal-block-1",
        )
    with pytest.raises(PilotRunReadinessError, match="serialized"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="typed-readiness-bypass",
            execution_mode=PilotExecutionMode.FORMAL,
            readiness_inputs=inputs,
            readiness_report=report,
            comparison_block_id="formal-block-2",
        )
    assert not (
        tmp_path
        / "runs"
        / "meas0"
        / "pilot"
        / "formal-block-1"
        / "formal-must-not-start"
    ).exists()


def test_comparison_block_is_formal_only_and_validated_before_creation(
    tmp_path: Path,
) -> None:
    lock_path = _prepare(tmp_path)
    with pytest.raises(PilotRunReadinessError, match="foundation"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="foundation-cannot-look-formal",
            comparison_block_id="formal-looking-block",
        )
    with pytest.raises(PilotRunReadinessError, match="comparison block"):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="formal-missing-block",
            execution_mode=PilotExecutionMode.FORMAL,
            readiness_bundle_path=tmp_path / "missing.json",
        )
    assert not (tmp_path / "runs" / "meas0" / "pilot").exists()


def test_synthetic_guard_pass_cannot_relabel_foundation_backend_as_formal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Contract-only test; it is not evidence of real formal readiness."""

    lock_path = _prepare(tmp_path)
    inputs = FormalReadinessInputs(
        formal_artifact_layout=FormalArtifactLayout(
            comparison_block_id="synthetic-formal-block",
            gold_directory="gold",
            gold_manifest_path="gold/manifest.json",
            gold_mount_manifest_path="gold/mount_manifest.json",
        )
    )
    bundle_path = tmp_path / "synthetic-readiness.json"
    bundle_path.write_text(
        json.dumps(FormalReadinessBundle.create(inputs).to_dict()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "biofield.meas0_pilot_run._require_formal_execution_ready",
        lambda **_kwargs: None,
    )

    with pytest.raises(
        PilotRunReadinessError,
        match="formal execution backend is unavailable",
    ):
        execute_pilot_run(
            lock_path=lock_path,
            output_directory=tmp_path / "runs",
            run_id="must-not-be-created",
            execution_mode=PilotExecutionMode.FORMAL,
            readiness_bundle_path=bundle_path,
            comparison_block_id="synthetic-formal-block",
        )
    assert not (
        tmp_path / "runs" / "meas0" / "pilot" / "synthetic-formal-block"
    ).exists()


def test_synthetic_formal_seal_is_mode_aware_but_not_replayed_as_foundation(
    tmp_path: Path,
) -> None:
    """Artifact-contract test only; no formal evaluator is executed."""

    store = PilotRunStore.create(
        tmp_path / "runs",
        "synthetic-package",
        comparison_block_id="synthetic-block",
    )
    store.write_json(
        "config.json",
        {
            "execution_mode": "formal",
            "formal_pilot": True,
            "claim_limit": FORMAL_CLAIM_LIMIT,
        },
    )
    seal = store.finalize(
        status="completed",
        metadata={"synthetic_contract_test_only": True},
        execution_mode=PilotExecutionMode.FORMAL,
    )
    assert seal["execution_mode"] == "formal"
    assert seal["formal_pilot"] is True
    assert seal["claim_limit"] == FORMAL_CLAIM_LIMIT
    with pytest.raises(PilotRunReadinessError, match="formal replay backend"):
        replay_pilot_run(store.run_directory)
    with pytest.raises(PilotRunReadinessError, match="formal summarize backend"):
        summarize_pilot_run(store.run_directory)
