from __future__ import annotations

import json
from pathlib import Path

import pytest

from biofield.artifacts import (
    ArtifactExistsError,
    ArtifactSerializationError,
    InvalidArtifactPath,
    RunArtifactStore,
)
from biofield.contracts import RequirementSpec, TaskSpec


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="fixture-1",
        requirement_schema_version=1,
        goal="Exercise artifact serialization",
        requirements=(RequirementSpec("result", "Produce a result"),),
        acceptance_rules=("result is satisfied",),
    )


def test_run_outputs_are_isolated_and_can_be_read_back(tmp_path: Path) -> None:
    output_directory = tmp_path / "explicit-runs"
    store = RunArtifactStore.create(
        output_directory=output_directory,
        experiment_id="b0",
        run_id="seed-7",
    )

    store.write_config(_task())
    store.append_event({"event_id": "event-1", "cycle": 0, "accepted": False})
    store.append_event({"event_id": "event-2", "cycle": 1, "accepted": True})
    store.write_metrics({"completion": 1.0, "cycles": [0, 1]})
    store.write_summary("# B0 seed 7\n\nCompleted deterministically.\n")

    expected = output_directory / "b0" / "seed-7"
    assert store.run_directory == expected.resolve()
    assert sorted(path.name for path in expected.iterdir()) == [
        "artifacts",
        "config.json",
        "events.jsonl",
        "metrics.json",
        "summary.md",
    ]
    assert store.read_config()["task_id"] == "fixture-1"
    assert store.read_events() == (
        {"accepted": False, "cycle": 0, "event_id": "event-1"},
        {"accepted": True, "cycle": 1, "event_id": "event-2"},
    )
    assert store.read_metrics() == {"completion": 1.0, "cycles": [0, 1]}
    assert store.read_summary().startswith("# B0 seed 7")
    assert not list(expected.glob(".*.tmp"))


def test_same_run_cannot_silently_overwrite_existing_output(tmp_path: Path) -> None:
    output_directory = tmp_path / "runs"
    first = RunArtifactStore.create(output_directory, "a0", "pilot")
    first.write_config({"model": "local-small-v1"})

    with pytest.raises(ArtifactExistsError, match="already exists"):
        RunArtifactStore.create(output_directory, "a0", "pilot")

    assert first.read_config() == {"model": "local-small-v1"}

    # Repeated experiments remain possible when they use an explicit new run ID.
    second = RunArtifactStore.create(output_directory, "a0", "pilot-2")
    assert second.run_directory != first.run_directory


def test_atomic_result_files_are_write_once(tmp_path: Path) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "c1", "seed-0")
    store.write_metrics({"regret": 0.25})

    with pytest.raises(ArtifactExistsError, match="metrics.json"):
        store.write_metrics({"regret": 999})

    assert store.read_metrics() == {"regret": 0.25}


@pytest.mark.parametrize(
    ("experiment_id", "run_id"),
    [
        ("../escape", "run"),
        ("/absolute", "run"),
        ("experiment", "../escape"),
        ("experiment", "nested/run"),
        ("experiment", r"nested\run"),
        (".", "run"),
        ("experiment", ".."),
    ],
)
def test_path_traversal_identifiers_are_rejected(
    tmp_path: Path,
    experiment_id: str,
    run_id: str,
) -> None:
    output_directory = tmp_path / "runs"

    with pytest.raises(InvalidArtifactPath):
        RunArtifactStore.create(output_directory, experiment_id, run_id)

    assert not (tmp_path / "escape").exists()


def test_symlinked_experiment_directory_cannot_escape_output_root(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "runs"
    outside = tmp_path / "outside"
    output_directory.mkdir()
    outside.mkdir()
    (output_directory / "a0").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidArtifactPath, match="symbolic link"):
        RunArtifactStore.create(output_directory, "a0", "pilot")

    assert not (outside / "pilot").exists()


def test_json_inputs_must_be_mappings_or_to_dict_contracts(tmp_path: Path) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "b0", "invalid-json")

    with pytest.raises(ArtifactSerializationError, match="mapping or expose to_dict"):
        store.write_config(["not", "an", "object"])
    with pytest.raises(ArtifactSerializationError, match="valid JSON"):
        store.write_metrics({"not_finite": float("nan")})

    assert not (store.run_directory / "config.json").exists()
    assert not (store.run_directory / "metrics.json").exists()


def test_events_file_contains_one_complete_json_object_per_line(tmp_path: Path) -> None:
    store = RunArtifactStore.create(tmp_path / "runs", "e0", "replay")
    for index in range(3):
        store.append_event({"event_id": f"e-{index}", "payload": {"index": index}})

    lines = (store.run_directory / "events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["event_id"] for line in lines] == ["e-0", "e-1", "e-2"]
