from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from biofield.meas0_confirmatory_store_v3 import (
    CONFIRMATORY_COMMITMENT_STORE_FILES,
    ConfirmatoryCommitmentStoreError,
    SimulatedConfirmatoryCommitmentCheckpoint,
    SimulatedConfirmatoryCommitmentStore,
    resume_simulated_confirmatory_commitments,
)
from biofield.meas0_confirmatory_v3 import (
    SimulatedConfirmatoryCommitmentPackage,
)
from test_meas0_confirmatory_v3 import _authorization, _commitments, _ledger


@pytest.fixture(scope="module")
def confirmatory_sources():
    authorization = _authorization()
    commitments = _commitments(authorization=authorization)
    ledger = _ledger()
    package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    return authorization, commitments, ledger, package


def test_checkpoint_resume_rederives_exact_package(confirmatory_sources) -> None:
    authorization, commitments, ledger, expected = confirmatory_sources
    checkpoint = SimulatedConfirmatoryCommitmentCheckpoint.create(
        authorization=authorization,
        completed_commitments=commitments[:360],
        stage_cost_ledger=ledger,
    )

    assert checkpoint.next_execution_index == 360
    assert checkpoint.claim_scope == "simulated_nonclaim"
    assert checkpoint.execution_verified is False
    assert checkpoint.outcome_package_closed is False
    assert (
        SimulatedConfirmatoryCommitmentCheckpoint.restore_from_typed_sources(
            checkpoint.to_dict(),
            authorization=authorization,
            completed_commitments=commitments[:360],
            stage_cost_ledger=ledger,
        )
        == checkpoint
    )
    assert (
        resume_simulated_confirmatory_commitments(
            checkpoint=checkpoint,
            authorization=authorization,
            remaining_commitments=commitments[360:],
            stage_cost_ledger=ledger,
        )
        == expected
    )


def test_checkpoint_rejects_reorder_cross_authorization_and_rehash(
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, _ = confirmatory_sources
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="prefix|ordered"):
        SimulatedConfirmatoryCommitmentCheckpoint.create(
            authorization=authorization,
            completed_commitments=(
                commitments[1],
                commitments[0],
                *commitments[2:10],
            ),
            stage_cost_ledger=ledger,
        )

    other = _authorization("offline.other")
    with pytest.raises(
        ConfirmatoryCommitmentStoreError,
        match="authorization|prefix",
    ):
        SimulatedConfirmatoryCommitmentCheckpoint.create(
            authorization=other,
            completed_commitments=commitments[:10],
            stage_cost_ledger=ledger,
        )

    checkpoint = SimulatedConfirmatoryCommitmentCheckpoint.create(
        authorization=authorization,
        completed_commitments=commitments[:10],
        stage_cost_ledger=ledger,
    )
    with pytest.raises(ConfirmatoryCommitmentStoreError):
        replace(checkpoint, next_execution_index=11)
    tampered = checkpoint.to_dict()
    tampered["next_execution_index"] = 11
    with pytest.raises(ConfirmatoryCommitmentStoreError):
        SimulatedConfirmatoryCommitmentCheckpoint.restore_from_typed_sources(
            tampered,
            authorization=authorization,
            completed_commitments=commitments[:10],
            stage_cost_ledger=ledger,
        )


def test_resume_rejects_missing_extra_or_wrong_prefix(confirmatory_sources) -> None:
    authorization, commitments, ledger, _ = confirmatory_sources
    checkpoint = SimulatedConfirmatoryCommitmentCheckpoint.create(
        authorization=authorization,
        completed_commitments=commitments[:360],
        stage_cost_ledger=ledger,
    )
    for changed in (
        commitments[361:],
        commitments[359:],
        tuple(reversed(commitments[360:])),
    ):
        with pytest.raises(ConfirmatoryCommitmentStoreError):
            resume_simulated_confirmatory_commitments(
                checkpoint=checkpoint,
                authorization=authorization,
                remaining_commitments=changed,
                stage_cost_ledger=ledger,
            )


def test_store_atomic_publish_and_typed_restore(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    published = store.publish(
        package_id="pytest-confirmatory-package",
        package=package,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )

    assert published.parent == tmp_path / ".objects"
    assert tuple(sorted(item.name for item in published.iterdir())) == tuple(
        sorted(CONFIRMATORY_COMMITMENT_STORE_FILES)
    )
    assert (
        store.restore(
            package_id="pytest-confirmatory-package",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
        == package
    )
    manifest = json.loads((published / "manifest.json").read_bytes())
    assert manifest["claim_scope"] == "simulated_nonclaim"
    assert manifest["typed_source_restore_required"] is True
    assert manifest["fresh_process_restore_ready"] is False
    assert manifest["execution_verified"] is False
    assert manifest["cost_verified"] is False
    assert manifest["outcome_package_closed"] is False


def test_store_is_write_once_and_concurrent_publish_has_one_winner(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)

    def publish():
        return store.publish(
            package_id="pytest-race",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: _capture(publish), range(2)))
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert (
        sum(isinstance(item, ConfirmatoryCommitmentStoreError) for item in outcomes)
        == 1
    )
    assert (
        store.restore(
            package_id="pytest-race",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
        == package
    )
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="exists|write-once"):
        publish()


def _capture(operation):
    try:
        return operation()
    except Exception as error:
        return error


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "extra",
        "tamper",
        "symlink",
        "hardlink",
        "noncanonical",
        "duplicate_key",
    ),
)
def test_store_restore_rejects_file_set_and_content_attacks(
    tmp_path,
    confirmatory_sources,
    mutation: str,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    directory = store.publish(
        package_id=f"pytest-attack-{mutation}",
        package=package,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    if mutation == "missing":
        (directory / "package.json").unlink()
    elif mutation == "extra":
        (directory / "unexpected.json").write_text("{}", encoding="utf-8")
    elif mutation == "tamper":
        raw = json.loads((directory / "package.json").read_bytes())
        raw["formal_eligible"] = True
        (directory / "package.json").write_text(
            json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "symlink":
        target = directory / "package.json"
        original = target.read_bytes()
        target.unlink()
        outside = tmp_path / "outside-package.json"
        outside.write_bytes(original)
        target.symlink_to(outside)
    elif mutation == "hardlink":
        target = directory / "package.json"
        outside = tmp_path / "outside-hardlink.json"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        os.link(outside, target)
    elif mutation == "noncanonical":
        (directory / "package.json").write_bytes(b'{ "x": 1 }\n')
    else:
        (directory / "package.json").write_bytes(b'{"x":1,"x":2}\n')

    with pytest.raises(ConfirmatoryCommitmentStoreError):
        store.restore(
            package_id=f"pytest-attack-{mutation}",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )


def test_store_rejects_path_escape_and_mixed_typed_sources(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="package_id"):
        store.publish(
            package_id="../escape",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )

    store.publish(
        package_id="pytest-mixed",
        package=package,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    with pytest.raises(ConfirmatoryCommitmentStoreError):
        store.restore(
            package_id="pytest-mixed",
            authorization=_authorization("offline.other"),
            commitments=commitments,
            stage_cost_ledger=ledger,
        )


def test_failed_preflight_leaves_no_partial_target(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, _ = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)

    with pytest.raises(ConfirmatoryCommitmentStoreError):
        store.publish(
            package_id="pytest-no-partial",
            package=object(),
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
    assert not (tmp_path / ".reservations" / "pytest-no-partial").exists()


def test_store_reservation_is_no_replace_and_persists_after_object_deletion(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    occupied = tmp_path / ".reservations" / "pytest-occupied"
    occupied.write_bytes(b"")
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="race"):
        store.publish(
            package_id="pytest-occupied",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
    assert occupied.read_bytes() == b""

    published = store.publish(
        package_id="pytest-tombstone",
        package=package,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    for item in published.iterdir():
        item.unlink()
    published.rmdir()
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="race"):
        store.publish(
            package_id="pytest-tombstone",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )


def test_store_fails_closed_if_root_path_is_replaced(
    tmp_path,
    confirmatory_sources,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    original = tmp_path.with_name(f"{tmp_path.name}-original")
    outside = tmp_path.with_name(f"{tmp_path.name}-outside")
    tmp_path.rename(original)
    outside.mkdir()
    tmp_path.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ConfirmatoryCommitmentStoreError, match="identity"):
            store.publish(
                package_id="pytest-root-swap",
                package=package,
                authorization=authorization,
                commitments=commitments,
                stage_cost_ledger=ledger,
            )
        assert tuple(outside.iterdir()) == ()
    finally:
        tmp_path.unlink()
        original.rename(tmp_path)
        outside.rmdir()


@pytest.mark.parametrize("internal_name", (".objects", ".reservations"))
def test_store_fails_closed_if_pinned_internal_directory_is_replaced(
    tmp_path,
    confirmatory_sources,
    internal_name: str,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    internal = tmp_path / internal_name
    original = tmp_path / f"{internal_name}-original"
    internal.rename(original)
    internal.mkdir()
    try:
        with pytest.raises(ConfirmatoryCommitmentStoreError, match="identity"):
            store.publish(
                package_id=f"pytest-internal-swap-{internal_name[1:]}",
                package=package,
                authorization=authorization,
                commitments=commitments,
                stage_cost_ledger=ledger,
            )
    finally:
        internal.rmdir()
        original.rename(internal)


def test_store_recovers_when_link_commits_then_reports_an_error(
    tmp_path,
    confirmatory_sources,
    monkeypatch,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    real_link = os.link

    def commit_then_raise(*args, **kwargs):
        real_link(*args, **kwargs)
        raise OSError("injected error after successful link")

    monkeypatch.setattr(os, "link", commit_then_raise)
    published = store.publish(
        package_id="pytest-commit-uncertain",
        package=package,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    assert published.is_dir()
    assert (
        store.restore(
            package_id="pytest-commit-uncertain",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
        == package
    )
    assert not tuple((tmp_path / ".reservations").glob(".*.tmp"))


def test_store_preserves_committed_object_after_base_exception(
    tmp_path,
    confirmatory_sources,
    monkeypatch,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    real_link = os.link

    def commit_then_interrupt(*args, **kwargs):
        real_link(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", commit_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.publish(
            package_id="pytest-base-exception",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
    assert (
        store.restore(
            package_id="pytest-base-exception",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
        == package
    )
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="race"):
        store.publish(
            package_id="pytest-base-exception",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )


def test_store_does_not_report_success_if_staged_object_is_tampered_at_commit(
    tmp_path,
    confirmatory_sources,
    monkeypatch,
) -> None:
    authorization, commitments, ledger, package = confirmatory_sources
    store = SimulatedConfirmatoryCommitmentStore(tmp_path)
    real_link = os.link

    def tamper_then_commit(*args, **kwargs):
        object_directories = tuple((tmp_path / ".objects").iterdir())
        assert len(object_directories) == 1
        package_path = object_directories[0] / "package.json"
        raw = json.loads(package_path.read_bytes())
        raw["formal_eligible"] = True
        package_path.write_text(
            json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return real_link(*args, **kwargs)

    monkeypatch.setattr(os, "link", tamper_then_commit)
    with pytest.raises(ConfirmatoryCommitmentStoreError, match="changed"):
        store.publish(
            package_id="pytest-stage-tamper",
            package=package,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
    with pytest.raises(ConfirmatoryCommitmentStoreError):
        store.restore(
            package_id="pytest-stage-tamper",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )
