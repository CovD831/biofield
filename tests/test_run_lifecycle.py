from __future__ import annotations

from pathlib import Path

import pytest

from biofield.artifacts import (
    ArtifactSerializationError,
    RunArtifactSchemas,
    RunArtifactStore,
    RunFinalizedError,
)
from biofield.contracts import RunTerminalStatus


SCHEMAS = RunArtifactSchemas(
    config={
        "type": "object",
        "additionalProperties": False,
        "required": ["experiment"],
        "properties": {"experiment": {"const": "f0"}},
    },
    event={
        "type": "object",
        "additionalProperties": False,
        "required": ["event_id", "event_type"],
        "properties": {
            "event_id": {"type": "string", "minLength": 1},
            "event_type": {"type": "string", "minLength": 1},
        },
    },
    metrics={
        "type": "object",
        "additionalProperties": False,
        "required": ["cycles"],
        "properties": {"cycles": {"type": "integer", "minimum": 0}},
    },
)


def test_strict_run_schema_rejects_invalid_config_event_and_metrics(
    tmp_path: Path,
) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "f0", "strict", schemas=SCHEMAS)

    with pytest.raises(ArtifactSerializationError, match="config schema"):
        store.write_config({"experiment": "wrong"})

    store.write_config({"experiment": "f0"})
    with pytest.raises(ArtifactSerializationError, match="event schema"):
        store.append_event({"event_id": "missing-type"})
    with pytest.raises(ArtifactSerializationError, match="metrics schema"):
        store.write_metrics({"cycles": -1})

    assert store.read_events() == ()


def test_finalize_requires_complete_outputs_and_seals_the_run(tmp_path: Path) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "f0", "complete", schemas=SCHEMAS)
    store.write_config({"experiment": "f0"})
    store.append_event({"event_id": "event-1", "event_type": "started"})

    with pytest.raises(ArtifactSerializationError, match="metrics.json"):
        store.finalize(
            status=RunTerminalStatus.COMPLETED,
            reason="done",
            final_state={"complete": True},
        )

    store.write_metrics({"cycles": 1})
    store.write_summary("# Complete\n")
    finalization = store.finalize(
        status=RunTerminalStatus.COMPLETED,
        reason="all required evidence accepted",
        final_state={"complete": True, "revision": 1},
    )

    assert finalization.status is RunTerminalStatus.COMPLETED
    assert finalization.event_count == 1
    assert set(finalization.file_sha256) == {
        "config.json",
        "events.jsonl",
        "metrics.json",
        "summary.md",
    }
    assert all(len(value) == 64 for value in finalization.file_sha256.values())
    assert len(finalization.final_state_sha256) == 64
    assert store.read_finalization() == finalization.to_dict()

    with pytest.raises(RunFinalizedError, match="finalized"):
        store.append_event({"event_id": "late", "event_type": "late"})
    with pytest.raises(RunFinalizedError, match="finalized"):
        store.finalize(
            status=RunTerminalStatus.COMPLETED,
            reason="again",
            final_state={"complete": True},
        )

