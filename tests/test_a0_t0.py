from __future__ import annotations

from biofield.a0_t0 import build_t0_arms, summarize_t0
from biofield.a0_runner import ProbeResponse
from biofield.probe_assets import ProbeAssetResolver


def test_t0_builds_two_identical_content_repeats_per_task() -> None:
    resolver = ProbeAssetResolver()
    arms = build_t0_arms(
        ("software_release_readiness", "cold_chain_readiness"),
        repeats=2,
    )

    assert len(arms) == 4
    assert len({arm.run_id for arm in arms}) == 4
    for task_id in ("software_release_readiness", "cold_chain_readiness"):
        task_arms = [arm for arm in arms if arm.task_id == task_id]
        assert len(task_arms) == 2
        assert len({resolver.resolve(arm).request_fingerprint for arm in task_arms}) == 1


def test_t0_summary_distinguishes_exact_and_signature_repeatability() -> None:
    arms = build_t0_arms(("software_release_readiness",), repeats=2)
    responses = (
        ProbeResponse(
            model_id="fake",
            requirement_id="fact_extraction",
            action_type="inspect",
            content='{"decision":"hold"}',
            input_tokens=10,
            output_tokens=5,
            evidence_score=0.5,
        ),
        ProbeResponse(
            model_id="fake",
            requirement_id="fact_extraction",
            action_type="inspect",
            content='{"decision":"hold","extra":true}',
            input_tokens=10,
            output_tokens=6,
            evidence_score=0.5,
        ),
    )

    metrics = summarize_t0(arms, responses)

    assert metrics["planned_calls"] == 2
    assert metrics["completed_calls"] == 2
    assert metrics["by_task"]["software_release_readiness"][
        "exact_content_repeatable"
    ] is False
    assert metrics["by_task"]["software_release_readiness"][
        "behavior_signature_repeatable"
    ] is True
