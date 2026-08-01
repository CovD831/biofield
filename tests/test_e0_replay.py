from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

import pytest

from biofield.artifacts import RunArtifactStore
from biofield.contracts import RunTerminalStatus
from biofield.e0 import (
    CheckpointExistsError,
    CheckpointPersistenceError,
    F0PublicEventAdapter,
    PublicEvent,
    PublicEventMigrationRegistry,
    PublicEventReplayError,
    PublicEventReplayer,
    PublicReplayCheckpointStore,
    PublicReplayCheckpoint,
)
from biofield.evidence_task import load_task_bundle
from biofield.f0 import DeterministicF0Executor, F0Experiment, F0RunConfig


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _sealed_f0_run(
    tmp_path: Path,
    *,
    run_id: str = "e0-source",
    action_budget: int = 3,
    max_cycles: int = 5,
    fail_on: str | None = None,
    invalid_on: str | None = None,
):
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    result = F0Experiment(
        bundle=bundle,
        executor=DeterministicF0Executor(
            bundle,
            fail_on_requirement=fail_on,
            invalid_on_requirement=invalid_on,
        ),
        config=F0RunConfig(
            output_directory=tmp_path / "runs",
            run_id=run_id,
            action_budget=action_budget,
            max_cycles=max_cycles,
        ),
    ).run()
    return result


def _event(
    event_id: str,
    sequence: int,
    *,
    event_type: str = "test",
    parent_ids: tuple[str, ...] = (),
    payload: dict[str, object] | None = None,
) -> PublicEvent:
    return PublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type=event_type,
        sequence=sequence,
        causal_parent_ids=parent_ids,
        payload=payload or {"value": sequence},
    )


def _replace_public_event(
    event: PublicEvent,
    *,
    sequence: int | None = None,
    parent_ids: tuple[str, ...] | None = None,
    payload: dict[str, object] | None = None,
) -> PublicEvent:
    return PublicEvent(
        schema_version=event.schema_version,
        event_id=event.event_id,
        event_type=event.event_type,
        sequence=event.sequence if sequence is None else sequence,
        causal_parent_ids=(
            event.causal_parent_ids if parent_ids is None else parent_ids
        ),
        payload=event.to_dict()["payload"] if payload is None else payload,
    )


def test_sealed_f0_run_adapts_to_one_replayable_public_event_stream(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)

    events = F0PublicEventAdapter.from_run_directory(source.run_directory)
    first = PublicEventReplayer.replay(events)
    second = PublicEventReplayer.replay(events)

    assert events[0].event_type == "run_started"
    assert events[-2].event_type == "run_settlement"
    assert events[-1].event_type == "run_terminal"
    assert events[-1].payload["source_final_state_sha256"] == source.final_state_sha256
    assert first == second
    assert first.terminal is True
    assert first.terminal_status == "completed"
    assert first.source_final_state_sha256 == source.final_state_sha256
    assert len(first.final_state_sha256) == 64


def test_exact_duplicate_event_is_idempotent() -> None:
    started = _event("started", 0, event_type="run_started")
    action = _event("action", 1, parent_ids=("started",))
    terminal = _event(
        "terminal",
        2,
        event_type="run_terminal",
        parent_ids=("action",),
        payload={"status": "completed", "source_final_state_sha256": "a" * 64},
    )

    normal = PublicEventReplayer.replay((started, action, terminal))
    duplicated = PublicEventReplayer.replay((started, action, action, terminal))

    assert duplicated == normal
    assert duplicated.applied_event_count == 3


def test_public_event_payload_is_deeply_immutable_and_detached_from_input() -> None:
    source_payload = {"nested": {"values": [1, 2]}}
    event = _event("immutable", 0, payload=source_payload)

    source_payload["nested"]["values"].append(3)

    assert event.to_dict()["payload"] == {"nested": {"values": [1, 2]}}
    with pytest.raises(TypeError):
        event.payload["new"] = "forbidden"  # type: ignore[index]
    with pytest.raises(AttributeError):
        event.payload["nested"]["values"].append(4)  # type: ignore[union-attr]


def test_conflicting_duplicate_event_fails_closed_with_machine_readable_reason() -> None:
    started = _event("started", 0, event_type="run_started")
    original = _event("same", 1, parent_ids=("started",), payload={"value": 1})
    conflict = _event("same", 1, parent_ids=("started",), payload={"value": 2})

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay((started, original, conflict))

    assert caught.value.code == "conflicting_duplicate"
    assert caught.value.event_id == "same"
    assert caught.value.input_index == 2


def test_missing_causal_parent_fails_closed() -> None:
    orphan = _event("orphan", 0, parent_ids=("missing",))

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay((orphan,))

    assert caught.value.code == "missing_causal_parent"
    assert caught.value.event_id == "orphan"


def test_event_after_terminal_fails_closed() -> None:
    started = _event("started", 0, event_type="run_started")
    terminal = _event(
        "terminal",
        1,
        event_type="run_terminal",
        parent_ids=("started",),
        payload={"status": "failed", "source_final_state_sha256": "b" * 64},
    )
    late = _event("late", 2, parent_ids=("terminal",))

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay((started, terminal, late))

    assert caught.value.code == "event_after_terminal"
    assert caught.value.event_id == "late"


def test_sequence_gap_or_reordering_fails_closed() -> None:
    started = _event("started", 0, event_type="run_started")
    skipped = _event("skipped", 2, parent_ids=("started",))

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay((started, skipped))

    assert caught.value.code == "sequence_mismatch"
    assert caught.value.event_id == "skipped"


def test_adapter_rejects_tampered_sealed_f0_artifact(tmp_path: Path) -> None:
    source = _sealed_f0_run(tmp_path)
    events_path = source.run_directory / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PublicEventReplayError) as caught:
        F0PublicEventAdapter.from_run_directory(source.run_directory)

    assert caught.value.code == "artifact_hash_mismatch"


def test_checkpoint_resume_is_equivalent_to_full_replay(tmp_path: Path) -> None:
    source = _sealed_f0_run(tmp_path)
    events = F0PublicEventAdapter.from_run_directory(source.run_directory)
    cut = len(events) // 2

    checkpoint = PublicEventReplayer.create_checkpoint(events[:cut])
    restored = PublicReplayCheckpoint.from_dict(checkpoint.to_dict())
    resumed = PublicEventReplayer.replay_from_checkpoint(restored, events[cut:])
    full = PublicEventReplayer.replay(events)

    assert resumed == full
    assert checkpoint.next_sequence == cut
    assert checkpoint.applied_event_ids == tuple(
        event.event_id for event in events[:cut]
    )
    assert checkpoint.applied_event_fingerprints == tuple(
        event.fingerprint for event in events[:cut]
    )
    assert len(checkpoint.checkpoint_sha256) == 64
    assert full.final_state_sha256 != source.final_state_sha256


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("next_sequence", 99),
        ("terminal_status", "forged"),
        ("checkpoint_sha256", "0" * 64),
    ],
)
def test_checkpoint_content_tampering_is_rejected(
    field: str,
    replacement: object,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    serialized = checkpoint.to_dict()
    serialized[field] = replacement

    with pytest.raises(PublicEventReplayError) as caught:
        PublicReplayCheckpoint.from_dict(serialized)

    assert caught.value.code == "checkpoint_hash_mismatch"


def test_checkpoint_rejects_tampered_applied_event_payload() -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    serialized = checkpoint.to_dict()
    serialized["applied_events"][0]["payload"]["value"] = "forged"

    with pytest.raises(PublicEventReplayError) as caught:
        PublicReplayCheckpoint.from_dict(serialized)

    assert caught.value.code == "checkpoint_event_mismatch"


def test_resume_rejects_conflicting_duplicate_against_checkpoint() -> None:
    started = _event("started", 0, event_type="run_started")
    action = _event("same", 1, parent_ids=("started",), payload={"value": 1})
    checkpoint = PublicEventReplayer.create_checkpoint((started, action))
    conflict = _event("same", 1, parent_ids=("started",), payload={"value": 2})

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay_from_checkpoint(checkpoint, (conflict,))

    assert caught.value.code == "conflicting_duplicate"
    assert caught.value.event_id == "same"


@pytest.mark.parametrize(
    ("event", "expected_code"),
    [
        (
            _event("orphan", 1, parent_ids=("missing",)),
            "missing_causal_parent",
        ),
        (
            _event("skipped", 2, parent_ids=("started",)),
            "sequence_mismatch",
        ),
    ],
)
def test_resume_rejects_invalid_parent_or_sequence(
    event: PublicEvent,
    expected_code: str,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay_from_checkpoint(checkpoint, (event,))

    assert caught.value.code == expected_code
    assert caught.value.event_id == event.event_id


def test_resume_rejects_new_event_after_terminal_checkpoint() -> None:
    started = _event("started", 0, event_type="run_started")
    terminal = _event(
        "terminal",
        1,
        event_type="run_terminal",
        parent_ids=("started",),
        payload={"status": "completed", "source_final_state_sha256": "c" * 64},
    )
    checkpoint = PublicEventReplayer.create_checkpoint((started, terminal))
    late = _event("late", 2, parent_ids=("terminal",))

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay_from_checkpoint(checkpoint, (late,))

    assert caught.value.code == "event_after_terminal"
    assert caught.value.event_id == "late"


def test_new_f0_run_emits_native_semantic_public_events_and_rebuilds_terminal_projection(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    raw_events = tuple(
        json.loads(line)
        for line in (source.run_directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert all(event["schema_version"] == 1 for event in raw_events)
    assert [event["sequence"] for event in raw_events] == list(
        range(len(raw_events))
    )
    assert all("causal_parent_ids" in event for event in raw_events)
    started_payload = raw_events[0]["payload"]
    assert started_payload["verifier_binding"]["verifier_id"]
    assert len(started_payload["verifier_binding"]["answer_key_contract_sha256"]) == 64
    assert "answer_key" not in started_payload

    adapted = F0PublicEventAdapter.from_run_directory(source.run_directory)
    assert [event.to_dict() for event in adapted] == list(raw_events)

    by_type = {
        event.event_type: event
        for event in adapted
        if event.event_type
        in {"action", "evidence", "feedback", "residual", "run_settlement", "run_terminal"}
    }
    assert by_type["evidence"].causal_parent_ids == (by_type["action"].event_id,)
    assert set(by_type["feedback"].causal_parent_ids) == {
        by_type["action"].event_id,
        by_type["evidence"].event_id,
    }
    assert by_type["residual"].causal_parent_ids == (
        by_type["feedback"].event_id,
    )
    assert by_type["run_terminal"].causal_parent_ids == (
        by_type["run_settlement"].event_id,
    )

    replayed = PublicEventReplayer.replay(adapted)
    assert replayed.primitive_replay_verified is True
    assert replayed.evidence_feedback_verified is True
    assert replayed.public_terminal_projection is not None
    assert replayed.public_terminal_projection["status"] == "completed"
    assert replayed.public_terminal_projection_to_dict()["residual"] == (
        source.residual.to_dict()
    )
    assert (
        replayed.public_terminal_projection_sha256
        == source.final_state_sha256
        == replayed.source_final_state_sha256
    )


@pytest.mark.parametrize(
    (
        "expected_status",
        "action_budget",
        "max_cycles",
        "fail_on",
        "invalid_on",
    ),
    [
        ("completed", 3, 5, None, None),
        ("failed", 3, 5, "contradiction_resolution", None),
        ("budget_exhausted", 1, 5, None, None),
        ("max_cycles", 2, 2, None, "fact_extraction"),
    ],
)
def test_native_v2_primitive_replay_rebuilds_all_terminal_paths(
    tmp_path: Path,
    expected_status: str,
    action_budget: int,
    max_cycles: int,
    fail_on: str | None,
    invalid_on: str | None,
) -> None:
    source = _sealed_f0_run(
        tmp_path,
        run_id=f"e0-{expected_status}",
        action_budget=action_budget,
        max_cycles=max_cycles,
        fail_on=fail_on,
        invalid_on=invalid_on,
    )
    events = F0PublicEventAdapter.from_run_directory(source.run_directory)

    replayed = PublicEventReplayer.replay(events)

    assert source.status.value == expected_status
    assert replayed.terminal_status == expected_status
    assert replayed.primitive_replay_verified is True
    assert replayed.evidence_feedback_verified is True
    assert replayed.public_terminal_projection is not None
    assert replayed.public_terminal_projection["status"] == expected_status
    assert (
        replayed.public_terminal_projection_sha256
        == source.final_state_sha256
        == replayed.source_final_state_sha256
    )


def test_terminal_checkpoint_preserves_projection_when_exact_duplicate_is_retried(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = F0PublicEventAdapter.from_run_directory(source.run_directory)
    checkpoint = PublicEventReplayer.create_checkpoint(events)

    resumed = PublicEventReplayer.replay_from_checkpoint(
        checkpoint,
        (events[-1],),
    )

    assert resumed == PublicEventReplayer.replay(events)


def test_primitive_replay_rejects_missing_evidence_even_if_graph_is_repaired(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    original = F0PublicEventAdapter.from_run_directory(source.run_directory)
    evidence_id = next(
        event.event_id for event in original if event.event_type == "evidence"
    )
    without_evidence = tuple(
        _replace_public_event(
            event,
            sequence=index,
            parent_ids=tuple(
                parent_id
                for parent_id in event.causal_parent_ids
                if parent_id != evidence_id
            ),
        )
        for index, event in enumerate(
            event for event in original if event.event_id != evidence_id
        )
    )

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(without_evidence)

    assert caught.value.code == "primitive_missing_evidence"


def test_primitive_replay_rejects_missing_settlement_after_graph_repair(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    original = F0PublicEventAdapter.from_run_directory(source.run_directory)
    settlement = next(
        event for event in original if event.event_type == "run_settlement"
    )
    without_settlement = tuple(
        _replace_public_event(
            event,
            sequence=index,
            parent_ids=(
                settlement.causal_parent_ids
                if event.event_type == "run_terminal"
                else event.causal_parent_ids
            ),
        )
        for index, event in enumerate(
            event for event in original if event.event_id != settlement.event_id
        )
    )

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(without_settlement)

    assert caught.value.code == "primitive_missing_settlement"
    assert caught.value.event_id == without_settlement[-1].event_id


def test_primitive_replay_rejects_changed_resource_payload(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "resource"
    )
    payload = events[index].to_dict()["payload"]
    payload["amount"] = 2
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_resource_error"


def test_primitive_replay_rejects_forged_feedback_disposition(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "feedback"
    )
    payload = events[index].to_dict()["payload"]
    payload["requirement_deltas"][0]["disposition"] = "rejected"
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_feedback_disposition_mismatch"


@pytest.mark.parametrize("tamper", ["content", "hash"])
def test_primitive_replay_rejects_evidence_content_or_hash_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "evidence"
    )
    payload = events[index].to_dict()["payload"]
    if tamper == "content":
        payload["evidence"] = {"forged": True}
    else:
        payload["artifact_sha256"] = "0" * 64
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_evidence_hash_mismatch"


def test_primitive_replay_rejects_forged_verifier_binding(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    payload = events[0].to_dict()["payload"]
    payload["verifier_binding"]["verifier_version"] = "forged"
    events[0] = _replace_public_event(events[0], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_verifier_binding_mismatch"


def test_prior_native_v1_stream_without_verifier_binding_remains_replayable(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    payload = events[0].to_dict()["payload"]
    payload["stream_kind"] = "f0.native.v1"
    payload.pop("verifier_binding")
    events[0] = _replace_public_event(events[0], payload=payload)

    replayed = PublicEventReplayer.replay(events)

    assert replayed.primitive_replay_verified is True
    assert replayed.evidence_feedback_verified is False


def test_frozen_verifier_rejects_forged_evidence_with_matching_forged_hash(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "evidence"
    )
    payload = events[index].to_dict()["payload"]
    payload["evidence"] = {"key_facts": []}
    encoded = (
        json.dumps(
            payload["evidence"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    payload["artifact_sha256"] = hashlib.sha256(encoded).hexdigest()
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_feedback_disposition_mismatch"


def test_primitive_replay_rejects_forged_residual_snapshot(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "residual"
    )
    payload = events[index].to_dict()["payload"]
    payload["snapshot"]["revision"] = 999
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_residual_mismatch"


def test_primitive_replay_rejects_forged_settlement_snapshot(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    events = list(F0PublicEventAdapter.from_run_directory(source.run_directory))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "run_settlement"
    )
    payload = events[index].to_dict()["payload"]
    payload["ledger"]["action_units"]["spent"] = "999"
    events[index] = _replace_public_event(events[index], payload=payload)

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventReplayer.replay(events)

    assert caught.value.code == "primitive_settlement_mismatch"


def test_native_adapter_rejects_evidence_artifact_hash_mismatch(
    tmp_path: Path,
) -> None:
    source = _sealed_f0_run(tmp_path)
    artifact_path = next((source.run_directory / "artifacts").glob("*.json"))
    artifact_path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(PublicEventReplayError) as caught:
        F0PublicEventAdapter.from_run_directory(source.run_directory)

    assert caught.value.code == "artifact_hash_mismatch"


def test_adapter_remains_compatible_with_legacy_sealed_f0_events(
    tmp_path: Path,
) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "f0-contract", "legacy")
    store.write_config(
        {
            "experiment_id": "f0",
            "protocol_version": 1,
            "task_id": "legacy-task",
        }
    )
    store.append_event(
        {
            "event_id": "allocation-000",
            "event_type": "allocation",
            "cycle": 0,
            "payload": {"requirement_id": "fact"},
        }
    )
    store.write_metrics({"spent_action_units": 1, "spent_tokens": 0})
    store.write_summary("# legacy F0\n")
    store.finalize(
        status=RunTerminalStatus.COMPLETED,
        reason="legacy fixture",
        final_state={"legacy": True},
    )

    adapted = F0PublicEventAdapter.from_run_directory(store.run_directory)
    replayed = PublicEventReplayer.replay(adapted)

    assert adapted[0].event_type == "run_started"
    assert adapted[-2].event_type == "run_settlement"
    assert adapted[-1].event_type == "run_terminal"
    assert replayed.terminal is True
    assert replayed.public_terminal_projection is None


def test_migration_registry_canonical_identity_preserves_hashes_and_parents() -> None:
    events = (
        _event("started", 0, event_type="run_started"),
        _event("action", 1, parent_ids=("started",)),
    )
    expected = {event.event_id: event.fingerprint for event in events}

    outcome = PublicEventMigrationRegistry.default().migrate_stream(
        tuple(event.to_dict() for event in events),
        expected_event_fingerprints=expected,
    )

    assert outcome.events == events
    assert outcome.source_schema_versions == (1,)
    assert outcome.primitive_semantics_preserved is True


def test_migration_registry_marks_legacy_sequence_adapter_as_non_primitive() -> None:
    legacy = (
        {
            "event_id": "allocation-000",
            "event_type": "allocation",
            "cycle": 0,
            "payload": {"requirement_id": "fact"},
        },
        {
            "event_id": "action-000",
            "event_type": "action",
            "cycle": 0,
            "payload": {"status": "succeeded"},
        },
    )

    outcome = PublicEventMigrationRegistry.default().migrate_stream(legacy)

    assert [event.sequence for event in outcome.events] == [0, 1]
    assert outcome.events[1].causal_parent_ids == ("allocation-000",)
    assert outcome.source_schema_versions == (0,)
    assert outcome.primitive_semantics_preserved is False


def test_migration_registry_rejects_unknown_schema_version() -> None:
    record = _event("future", 0).to_dict()
    record["schema_version"] = 999

    with pytest.raises(PublicEventReplayError) as caught:
        PublicEventMigrationRegistry.default().migrate_stream((record,))

    assert caught.value.code == "unknown_event_schema"


def test_migration_registry_rejects_non_idempotent_migrator() -> None:
    calls = 0

    def unstable(record: dict[str, object], context: dict[str, object]):
        nonlocal calls
        calls += 1
        return {
            "schema_version": 1,
            "event_id": record["event_id"],
            "event_type": "test",
            "sequence": context["sequence"],
            "causal_parent_ids": [],
            "payload": {"call": calls},
        }

    registry = PublicEventMigrationRegistry.default()
    registry.register(2, unstable, primitive_semantics_preserved=False)

    with pytest.raises(PublicEventReplayError) as caught:
        registry.migrate_stream(({"schema_version": 2, "event_id": "x"},))

    assert caught.value.code == "non_idempotent_migration"


def test_migration_registry_rejects_parent_or_hash_damage() -> None:
    registry = PublicEventMigrationRegistry.default()

    def orphan(record: dict[str, object], context: dict[str, object]):
        return {
            "schema_version": 1,
            "event_id": record["event_id"],
            "event_type": "test",
            "sequence": context["sequence"],
            "causal_parent_ids": ["missing"],
            "payload": {},
        }

    registry.register(2, orphan, primitive_semantics_preserved=False)
    with pytest.raises(PublicEventReplayError) as parent_error:
        registry.migrate_stream(({"schema_version": 2, "event_id": "x"},))
    assert parent_error.value.code == "migration_causal_integrity"

    event = _event("stable", 0)
    with pytest.raises(PublicEventReplayError) as hash_error:
        PublicEventMigrationRegistry.default().migrate_stream(
            (event.to_dict(),),
            expected_event_fingerprints={"stable": "0" * 64},
        )
    assert hash_error.value.code == "migration_hash_mismatch"


def test_checkpoint_store_round_trip_resume_matches_memory_path(
    tmp_path: Path,
) -> None:
    started = _event("started", 0, event_type="run_started")
    action = _event("action", 1, parent_ids=("started",))
    terminal = _event(
        "terminal",
        2,
        event_type="run_terminal",
        parent_ids=("action",),
        payload={"status": "completed", "source_final_state_sha256": "d" * 64},
    )
    checkpoint = PublicEventReplayer.create_checkpoint((started, action))
    path = tmp_path / "checkpoint.json"

    receipt = PublicReplayCheckpointStore.write(path, checkpoint)
    loaded = PublicReplayCheckpointStore.load(
        path,
        expected_file_sha256=receipt.file_sha256,
    )

    assert loaded == checkpoint
    assert len(receipt.file_sha256) == 64
    assert PublicEventReplayer.replay_from_checkpoint(
        loaded,
        (terminal,),
    ) == PublicEventReplayer.replay((started, action, terminal))
    assert not list(tmp_path.glob(".checkpoint.json.*.tmp"))


def test_checkpoint_store_is_write_once(tmp_path: Path) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    path = tmp_path / "checkpoint.json"
    PublicReplayCheckpointStore.write(path, checkpoint)

    with pytest.raises(CheckpointExistsError):
        PublicReplayCheckpointStore.write(path, checkpoint)


def test_checkpoint_store_fsyncs_file_then_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    path = tmp_path / "checkpoint.json"
    real_fsync = os.fsync
    fsync_targets: list[str] = []

    def recording_fsync(descriptor: int) -> None:
        fsync_targets.append(
            "directory"
            if stat.S_ISDIR(os.fstat(descriptor).st_mode)
            else "file"
        )
        real_fsync(descriptor)

    monkeypatch.setattr("biofield.e0.os.fsync", recording_fsync)

    PublicReplayCheckpointStore.write(path, checkpoint)

    assert fsync_targets == ["file", "directory"]


def test_checkpoint_store_concurrent_writers_preserve_write_once(
    tmp_path: Path,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    path = tmp_path / "checkpoint.json"
    barrier = threading.Barrier(2)

    def write_once():
        barrier.wait()
        try:
            return PublicReplayCheckpointStore.write(path, checkpoint)
        except CheckpointExistsError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: write_once(), range(2)))

    assert sum(isinstance(result, CheckpointExistsError) for result in results) == 1
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert PublicReplayCheckpointStore.load(path) == checkpoint
    assert not list(tmp_path.glob(".checkpoint.json.*.tmp"))


def test_interrupted_checkpoint_publish_rejects_temporary_file_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    path = tmp_path / "checkpoint.json"
    observed: dict[str, object] = {}

    def interrupt_publish(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        del destination
        temporary_path = Path(source)
        observed["temporary_path"] = temporary_path
        with pytest.raises(CheckpointPersistenceError) as caught:
            PublicReplayCheckpointStore.load(temporary_path)
        observed["load_error_code"] = caught.value.code
        raise OSError("injected publish interruption")

    monkeypatch.setattr("biofield.e0.os.replace", interrupt_publish)

    with pytest.raises(CheckpointPersistenceError) as publish_error:
        PublicReplayCheckpointStore.write(path, checkpoint)

    assert publish_error.value.code == "checkpoint_publish_error"
    assert observed["load_error_code"] == "unpublished_checkpoint"
    assert not path.exists()
    assert not Path(observed["temporary_path"]).exists()
    assert not list(tmp_path.glob(".checkpoint.json.*.tmp"))


@pytest.mark.parametrize("tamper_mode", ["bytes", "expected_hash", "self_hash"])
def test_checkpoint_store_rejects_tampering(
    tmp_path: Path,
    tamper_mode: str,
) -> None:
    checkpoint = PublicEventReplayer.create_checkpoint(
        (_event("started", 0, event_type="run_started"),)
    )
    path = tmp_path / "checkpoint.json"
    receipt = PublicReplayCheckpointStore.write(path, checkpoint)
    expected_hash = receipt.file_sha256

    if tamper_mode == "bytes":
        path.write_bytes(path.read_bytes().replace(b'"started"', b'"forged"'))
    elif tamper_mode == "expected_hash":
        expected_hash = "0" * 64
    else:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["content_sha256"] = "0" * 64
        path.write_text(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        expected_hash = None

    with pytest.raises(CheckpointPersistenceError) as caught:
        PublicReplayCheckpointStore.load(
            path,
            expected_file_sha256=expected_hash,
        )

    assert caught.value.code in {
        "checkpoint_file_hash_mismatch",
        "checkpoint_content_hash_mismatch",
    }
