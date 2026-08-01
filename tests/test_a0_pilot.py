from __future__ import annotations

from pathlib import Path

from biofield.a0_pilot import (
    _git_snapshot,
    _source_hashes,
    execute_core_schedule,
    summarize_core_outcomes,
)
from biofield.a0_runner import ProbeResponse
from biofield.a0_schedule import A0ScheduledPair, build_core_schedule
from biofield.artifacts import RunArtifactStore
from biofield.model_probe import ProbeArm
from biofield.probe_assets import ProbeAssetResolver


class DeterministicAdapter:
    def __init__(self, failed_run_id: str | None = None) -> None:
        self.failed_run_id = failed_run_id

    def invoke(self, arm: ProbeArm) -> ProbeResponse:
        if arm.run_id == self.failed_run_id:
            raise RuntimeError("planned fake provider failure")
        requirement_id = (
            "contradiction_resolution"
            if arm.history_id == "history.specialized.v1"
            else "fact_extraction"
        )
        action_type = (
            "cross_check"
            if requirement_id == "contradiction_resolution"
            else "inspect"
        )
        return ProbeResponse(
            model_id="fake-model",
            requirement_id=requirement_id,
            action_type=action_type,
            content="{}",
            input_tokens=100,
            output_tokens=20,
            evidence_score=0.5,
        )


def _technical_schedule() -> tuple[A0ScheduledPair, ...]:
    return build_core_schedule(
        task_ids=("software_release_readiness",),
        agent_labels=("agent.a",),
        repeats=1,
        base_seed=4100,
    )


def test_execute_core_schedule_writes_every_planned_call_event(
    tmp_path: Path,
) -> None:
    schedule = _technical_schedule()
    store = RunArtifactStore.create(tmp_path, "a0", "technical-test")
    store.write_config({"evidence_level": "exploratory_technical"})

    outcomes = execute_core_schedule(
        schedule,
        adapter_factory=lambda _: DeterministicAdapter(),
        resolver=ProbeAssetResolver(),
        store=store,
    )

    assert len(outcomes) == 4
    events = store.read_events()
    assert len(events) == 8
    assert [event["call_index"] for event in events] == list(range(1, 9))
    assert all(event["status"] == "completed" for event in events)
    assert {event["pair_id"] for event in events} == {
        item.pair_id for item in schedule
    }
    for event in events:
        item = next(case for case in schedule if case.pair_id == event["pair_id"])
        expected_seed = (
            item.control_seed
            if event["condition"] == "control"
            else item.treatment_seed
        )
        assert event["effective_seed"] == expected_seed
        assert len(event["request_fingerprint"]) == 64


def test_failure_remains_in_place_and_does_not_suppress_paired_arm(
    tmp_path: Path,
) -> None:
    schedule = _technical_schedule()
    failed_run_id = schedule[0].contrast.control.run_id
    store = RunArtifactStore.create(tmp_path, "a0", "failure-test")

    outcomes = execute_core_schedule(
        schedule,
        adapter_factory=lambda _: DeterministicAdapter(failed_run_id),
        resolver=ProbeAssetResolver(),
        store=store,
    )

    events = store.read_events()
    assert len(events) == 8
    assert sum(event["status"] == "failed" for event in events) == 1
    failed = next(event for event in events if event["status"] == "failed")
    assert failed["run_id"] == failed_run_id
    assert failed["failure_type"] == "RuntimeError"
    assert failed["failure_message"] == "planned fake provider failure"
    paired = next(item for item in outcomes if item.case == schedule[0])
    assert paired.paired.control.status == "failed"
    assert paired.paired.treatment.status == "completed"


def test_summary_preserves_counts_signatures_scores_and_resource_usage() -> None:
    schedule = _technical_schedule()
    outcomes = execute_core_schedule(
        schedule,
        adapter_factory=lambda _: DeterministicAdapter(),
        resolver=ProbeAssetResolver(),
    )

    metrics = summarize_core_outcomes(schedule, outcomes)

    assert metrics["evidence_level"] == "exploratory_technical"
    assert metrics["scientific_claim_eligible"] is False
    assert metrics["planned_pairs"] == 4
    assert metrics["planned_calls"] == 8
    assert metrics["completed_calls"] == 8
    assert metrics["failed_calls"] == 0
    assert metrics["completed_pairs"] == 4
    assert metrics["total_input_tokens"] == 800
    assert metrics["total_output_tokens"] == 160
    assert set(metrics["by_contrast"]) == {
        "sampling_noise",
        "execution_history",
        "history_clear",
        "role_induction",
    }
    assert metrics["by_contrast"]["execution_history"][
        "joint_signature_changed_pairs"
    ] == 1


def test_source_snapshot_includes_the_action_bias_runner() -> None:
    experiment_root = Path(__file__).parents[1]

    hashes = _source_hashes(experiment_root)

    assert "src/biofield/a0_action_bias.py" in hashes
    assert len(hashes["src/biofield/a0_action_bias.py"]) == 64
    assert "src/biofield/a0_action_axis.py" in hashes
    assert len(hashes["src/biofield/a0_action_axis.py"]) == 64


def test_git_snapshot_discovers_the_standalone_repository_root(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Biofield Tests",
            "-c",
            "user.email=biofield-tests@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "untracked.txt").write_text("pending\n", encoding="utf-8")

    snapshot = _git_snapshot(tmp_path)

    assert snapshot["head"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert snapshot["repository_root"] == str(tmp_path.resolve())
    assert snapshot["repository_status"] == ["?? untracked.txt"]
