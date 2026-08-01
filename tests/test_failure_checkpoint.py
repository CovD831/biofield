from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.contracts import ResourceAmount
from biofield.failure_checkpoint import (
    FailureCheckpointExistsError,
    FailureCheckpointPersistenceError,
    FailureCheckpointStore,
    FailureReorganizationCheckpoint,
    create_failure_reorganization_checkpoint,
    resume_failure_reorganization,
)
from biofield.local_runtime import HarnessCycleError
from test_failure_reorganization_runtime import _replay, _run
from test_refusal_takeover_runtime import _inputs


def _checkpoint(events=None):
    result = _run()
    candidates, admission, multi, _ = _inputs()
    prefix = (
        tuple(events)
        if events is not None
        else result.events[
            : next(
                index
                for index, event in enumerate(result.events)
                if event.event_type == "failure_settlement"
            )
            + 1
        ]
    )
    return create_failure_reorganization_checkpoint(
        candidates=candidates,
        admission_policy=admission,
        multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        events=prefix,
    )


def _resume(checkpoint, suffix):
    candidates, admission, multi, _ = _inputs()
    return resume_failure_reorganization(
        checkpoint=checkpoint,
        candidates=candidates,
        admission_policy=admission,
        multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        suffix_events=tuple(suffix),
    )


def _contains_key(value, forbidden):
    if isinstance(value, dict):
        return any(
            key in forbidden or _contains_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _rehash(event, payload):
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return replace(event, payload=payload, payload_sha256=digest)


def test_checkpoint_is_minimal_public_projection_and_resume_matches_full_replay():
    result = _run()
    split = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "failure_settlement"
    ) + 1
    checkpoint = _checkpoint(result.events[:split])

    serialized = checkpoint.to_dict()
    assert "events" not in serialized
    assert "payload" not in serialized
    assert not _contains_key(
        serialized,
        {"values", "proposed_values", "committed_values", "changed_fields"},
    )
    assert checkpoint.next_public_state_revision == split
    assert checkpoint.last_event_id == result.events[split - 1].event_id
    assert checkpoint.authority == "harness_runtime"
    assert checkpoint.ledger_totals["tokens"]["shared_pool"] == "90"
    assert checkpoint.ledger_totals["tokens"]["spent"] == "10"
    assert all(
        len(item.public_projection_sha256) == 64
        for item in checkpoint.local_states
    )
    assert checkpoint.organization_parent_event_ids

    resumed = _resume(checkpoint, result.events[split:])
    replayed = _replay(result.events)

    assert resumed == replayed
    assert resumed.terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_checkpoint_prefix_and_suffix_integrity_fail_closed():
    result = _run()
    split = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "failure_settlement"
    ) + 1
    checkpoint = _checkpoint(result.events[:split])

    payload = checkpoint.to_dict()
    payload["prefix_sha256"] = "0" * 64
    with pytest.raises(HarnessCycleError, match="prefix binding"):
        FailureReorganizationCheckpoint.from_dict(payload)

    first_suffix = result.events[split]
    wrong_parent = replace(
        first_suffix,
        causal_parent_ids=(
            next(
                event.event_id
                for event in result.events[:split]
                if event.event_type == "failure_commitment_transition"
            ),
        ),
    )
    with pytest.raises(HarnessCycleError, match="suffix parent"):
        _resume(checkpoint, (wrong_parent, *result.events[split + 1 :]))

    duplicate_prefix_event = replace(
        result.events[0],
        public_state_revision=split,
    )
    with pytest.raises(HarnessCycleError, match="duplicate"):
        _resume(
            checkpoint,
            (duplicate_prefix_event, *result.events[split:]),
        )

    duplicate_suffix = (
        result.events[split],
        replace(
            result.events[split],
            public_state_revision=split + 1,
        ),
        *result.events[split + 1 :],
    )
    with pytest.raises(HarnessCycleError, match="duplicate"):
        _resume(checkpoint, duplicate_suffix)

    payload = first_suffix.to_dict()["payload"]
    payload["available_budget"][0]["amount"] = 89
    semantic_tamper = _rehash(first_suffix, payload)
    with pytest.raises(HarnessCycleError, match="semantics"):
        _resume(
            checkpoint,
            (semantic_tamper, *result.events[split + 1 :]),
        )


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("version", "version"),
        ("authority", "authority"),
        ("ledger", "Ledger"),
        ("local_state", "local-state public hash"),
        ("organization", "organization linkage"),
        ("commitment", "commitment lifecycle linkage"),
    ],
)
def test_checkpoint_public_projection_is_semantically_sealed(mode, message):
    payload = _checkpoint().to_dict()
    if mode == "version":
        payload["runtime_version"] = "failure-reorganization-forged"
    elif mode == "authority":
        payload["authority"] = "central_router"
    elif mode == "ledger":
        payload["ledger_totals"]["tokens"]["shared_pool"] = "89"
    elif mode == "local_state":
        payload["local_states"][0]["public_projection_sha256"] = "0" * 64
    elif mode == "organization":
        payload["organization_parent_event_ids"] = (
            payload["organization_parent_event_ids"][:1]
        )
    else:
        payload["lifecycles"][0]["commitment_id"] = "commitment-forged"
    content = {
        key: value
        for key, value in payload.items()
        if key != "checkpoint_sha256"
    }
    payload["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(
            content,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    with pytest.raises(HarnessCycleError, match=message):
        FailureReorganizationCheckpoint.from_dict(payload)


def test_checkpoint_rejects_configuration_tamper_and_terminal_resume():
    result = _run()
    checkpoint = _checkpoint()
    candidates, admission, multi, _ = _inputs()

    with pytest.raises(HarnessCycleError, match="configuration"):
        resume_failure_reorganization(
            checkpoint=checkpoint,
            candidates=candidates,
            admission_policy=replace(
                admission,
                policy_version="admission-policy-forged",
            ),
            multi_policy=multi,
            run_budget=(ResourceAmount("tokens", 100),),
            suffix_events=result.events[
                checkpoint.next_public_state_revision :
            ],
        )

    terminal_checkpoint = create_failure_reorganization_checkpoint(
        candidates=candidates,
        admission_policy=admission,
        multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        events=result.events,
    )
    assert terminal_checkpoint.terminal is True
    with pytest.raises(HarnessCycleError, match="terminal"):
        _resume(terminal_checkpoint, ())


def test_checkpoint_only_publishes_settled_or_terminal_boundaries():
    result = _run()
    candidates, admission, multi, _ = _inputs()

    for unsafe_events in ((), result.events[:5]):
        with pytest.raises(HarnessCycleError, match="boundary"):
            create_failure_reorganization_checkpoint(
                candidates=candidates,
                admission_policy=admission,
                multi_policy=multi,
                run_budget=(ResourceAmount("tokens", 100),),
                events=unsafe_events,
            )


def test_checkpoint_store_is_content_addressed_atomic_and_write_once(
    tmp_path: Path,
):
    checkpoint = _checkpoint()
    path = tmp_path / "failure-checkpoint.json"

    receipt = FailureCheckpointStore.write(path, checkpoint)
    loaded = FailureCheckpointStore.load(
        path,
        expected_file_sha256=receipt.file_sha256,
    )

    assert loaded == checkpoint
    assert len(receipt.file_sha256) == 64
    assert not list(tmp_path.glob(".failure-checkpoint.json.*.tmp"))
    with pytest.raises(FailureCheckpointExistsError):
        FailureCheckpointStore.write(path, checkpoint)


def test_checkpoint_store_fsyncs_file_before_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    checkpoint = _checkpoint()
    path = tmp_path / "failure-checkpoint.json"
    real_fsync = os.fsync
    targets = []

    def recording_fsync(descriptor):
        targets.append(
            "directory"
            if stat.S_ISDIR(os.fstat(descriptor).st_mode)
            else "file"
        )
        real_fsync(descriptor)

    monkeypatch.setattr("biofield.failure_checkpoint.os.fsync", recording_fsync)

    FailureCheckpointStore.write(path, checkpoint)

    assert targets == ["file", "directory"]


def test_checkpoint_store_concurrent_writers_preserve_write_once(
    tmp_path: Path,
):
    checkpoint = _checkpoint()
    path = tmp_path / "failure-checkpoint.json"
    barrier = threading.Barrier(2)

    def write_once():
        barrier.wait()
        try:
            return FailureCheckpointStore.write(path, checkpoint)
        except FailureCheckpointExistsError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: write_once(), range(2)))

    assert sum(
        isinstance(result, FailureCheckpointExistsError)
        for result in results
    ) == 1
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert FailureCheckpointStore.load(path) == checkpoint
    assert not list(tmp_path.glob(".failure-checkpoint.json.*.tmp"))


def test_interrupted_checkpoint_publish_never_exposes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    checkpoint = _checkpoint()
    path = tmp_path / "failure-checkpoint.json"
    observed = {}

    def interrupt_link(source, destination):
        del destination
        temporary = Path(source)
        observed["temporary"] = temporary
        with pytest.raises(FailureCheckpointPersistenceError) as caught:
            FailureCheckpointStore.load(temporary)
        observed["code"] = caught.value.code
        raise OSError("injected publish interruption")

    monkeypatch.setattr("biofield.failure_checkpoint.os.link", interrupt_link)

    with pytest.raises(FailureCheckpointPersistenceError) as caught:
        FailureCheckpointStore.write(path, checkpoint)

    assert caught.value.code == "checkpoint_publish_error"
    assert observed["code"] == "unpublished_checkpoint"
    assert not path.exists()
    assert not observed["temporary"].exists()
    assert not list(tmp_path.glob(".failure-checkpoint.json.*.tmp"))


@pytest.mark.parametrize("mode", ["bytes", "expected_file", "self_hash"])
def test_checkpoint_store_rejects_tamper(
    tmp_path: Path,
    mode: str,
):
    checkpoint = _checkpoint()
    path = tmp_path / "failure-checkpoint.json"
    receipt = FailureCheckpointStore.write(path, checkpoint)
    expected = receipt.file_sha256

    if mode == "bytes":
        path.write_bytes(path.read_bytes().replace(b'"failure-run-1"', b'"forged-run-1"'))
    elif mode == "expected_file":
        expected = "0" * 64
    else:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["checkpoint"]["checkpoint_sha256"] = "0" * 64
        content = {
            "format": envelope["format"],
            "format_version": envelope["format_version"],
            "checkpoint": envelope["checkpoint"],
        }
        envelope["content_sha256"] = hashlib.sha256(
            json.dumps(
                content,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        path.write_text(
            json.dumps(
                envelope,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        expected = None

    with pytest.raises(FailureCheckpointPersistenceError):
        FailureCheckpointStore.load(path, expected_file_sha256=expected)


def test_unpublished_temporary_checkpoint_is_never_loadable(tmp_path: Path):
    temporary = tmp_path / ".failure-checkpoint.json.interrupted.tmp"
    temporary.write_text("{}", encoding="utf-8")

    with pytest.raises(
        FailureCheckpointPersistenceError,
        match="unpublished",
    ):
        FailureCheckpointStore.load(temporary)
