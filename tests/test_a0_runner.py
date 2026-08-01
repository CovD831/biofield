from __future__ import annotations

from collections.abc import Callable

import pytest

from biofield.a0_runner import (
    BehaviorSignature,
    ProbeResponse,
    run_contrast,
)
from biofield.model_probe import ProbeArm, ProbeContrast, build_a0_contrasts


def _contrast(contrast_id: str) -> ProbeContrast:
    return next(
        contrast
        for contrast in build_a0_contrasts(ProbeArm.reference())
        if contrast.contrast_id == contrast_id
    )


def _response(
    requirement_id: str,
    action_type: str,
    *,
    input_tokens: int = 11,
    output_tokens: int = 7,
) -> ProbeResponse:
    return ProbeResponse(
        model_id="fake-model-v1",
        requirement_id=requirement_id,
        action_type=action_type,
        content=f"{requirement_id}:{action_type}",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class FakeAdapter:
    def __init__(
        self,
        outcomes: dict[str, ProbeResponse | Exception],
    ) -> None:
        self._outcomes = outcomes
        self.calls: list[ProbeArm] = []

    def invoke(self, arm: ProbeArm) -> ProbeResponse:
        self.calls.append(arm)
        outcome = self._outcomes[arm.run_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _clock(*values: float) -> Callable[[], float]:
    iterator = iter(values)
    return lambda: next(iterator)


def test_runner_executes_control_and_treatment_as_one_pair() -> None:
    contrast = _contrast("execution_history")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("evidence", "search"),
            contrast.treatment.run_id: _response(
                "verification",
                "check",
                input_tokens=13,
                output_tokens=5,
            ),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="control_first",
        clock=_clock(1.0, 1.01, 2.0, 2.025),
    )

    assert adapter.calls == [contrast.control, contrast.treatment]
    assert paired.contrast == contrast
    assert paired.records == (paired.control, paired.treatment)
    assert paired.control.status == "completed"
    assert paired.control.response == _response("evidence", "search")
    assert paired.control.input_tokens == 11
    assert paired.control.output_tokens == 7
    assert paired.control.latency_ms == pytest.approx(10.0)
    assert paired.treatment.status == "completed"
    assert paired.treatment.input_tokens == 13
    assert paired.treatment.output_tokens == 5
    assert paired.treatment.latency_ms == pytest.approx(25.0)


def test_runner_records_failure_and_still_executes_the_paired_arm() -> None:
    contrast = _contrast("system_prompt")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: RuntimeError("fake provider failure"),
            contrast.treatment.run_id: _response("analysis", "synthesize"),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="control_first",
        clock=_clock(3.0, 3.004, 4.0, 4.008),
    )

    assert adapter.calls == [contrast.control, contrast.treatment]
    assert paired.control.status == "failed"
    assert paired.control.response is None
    assert paired.control.failure_type == "RuntimeError"
    assert paired.control.failure_message == "fake provider failure"
    assert paired.control.input_tokens is None
    assert paired.control.output_tokens is None
    assert paired.control.latency_ms == pytest.approx(4.0)
    assert paired.treatment.status == "completed"


def test_sampling_contrast_exposes_a_same_condition_noise_signature() -> None:
    contrast = _contrast("sampling_noise")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("evidence", "search"),
            contrast.treatment.run_id: _response("verification", "check"),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="control_first",
        clock=_clock(0.0, 0.001, 1.0, 1.001),
    )

    signature = paired.sampling_noise_signature
    assert signature is not None
    assert signature.control == BehaviorSignature("evidence", "search")
    assert signature.treatment == BehaviorSignature("verification", "check")
    assert signature.changed is True


def test_identical_structured_actions_have_a_stable_noise_signature() -> None:
    contrast = _contrast("sampling_noise")
    response = _response("evidence", "search")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: response,
            contrast.treatment.run_id: response,
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="control_first",
        clock=_clock(0.0, 0.001, 1.0, 1.001),
    )

    assert paired.sampling_noise_signature is not None
    assert paired.sampling_noise_signature.changed is False
    assert paired.control.behavior_signature == paired.treatment.behavior_signature


def test_non_sampling_contrast_does_not_claim_a_noise_signature() -> None:
    contrast = _contrast("task_input")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("evidence", "search"),
            contrast.treatment.run_id: _response("evidence", "search"),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="control_first",
        clock=_clock(0.0, 0.001, 1.0, 1.001),
    )

    assert paired.sampling_noise_signature is None


def test_adapter_can_report_token_usage_as_explicitly_unknown() -> None:
    response = ProbeResponse(
        model_id="fake-model-v1",
        requirement_id="evidence",
        action_type="search",
        content="structured output",
        input_tokens=None,
        output_tokens=None,
    )

    assert response.input_tokens is None
    assert response.output_tokens is None


def test_runner_can_counterbalance_treatment_first_without_swapping_labels() -> None:
    contrast = _contrast("execution_history")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("fact_extraction", "inspect"),
            contrast.treatment.run_id: _response(
                "contradiction_resolution",
                "cross_check",
            ),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        execution_order="treatment_first",
        clock=_clock(1.0, 1.01, 2.0, 2.02),
    )

    assert adapter.calls == [contrast.treatment, contrast.control]
    assert paired.control.arm == contrast.control
    assert paired.treatment.arm == contrast.treatment
    assert paired.execution_order == "treatment_first"


def test_runner_records_an_explicit_unique_pair_id() -> None:
    contrast = _contrast("execution_history")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("fact_extraction", "inspect"),
            contrast.treatment.run_id: _response(
                "contradiction_resolution",
                "cross_check",
            ),
        }
    )

    paired = run_contrast(
        contrast,
        adapter,
        pair_id="software.agent-a.execution-history.repeat-01",
        pair_seed=7100,
        execution_order="control_first",
        clock=_clock(1.0, 1.01, 2.0, 2.02),
    )

    assert paired.pair_id == "software.agent-a.execution-history.repeat-01"
    assert paired.pair_seed == 7100
    assert paired.control.pair_id == paired.pair_id
    assert paired.treatment.pair_id == paired.pair_id
    assert paired.control.contrast_id == contrast.contrast_id
    assert paired.treatment.contrast_id == contrast.contrast_id


def test_runner_requires_an_explicit_counterbalancing_order() -> None:
    contrast = _contrast("execution_history")
    adapter = FakeAdapter(
        {
            contrast.control.run_id: _response("fact_extraction", "inspect"),
            contrast.treatment.run_id: _response("decision_synthesis", "synthesize"),
        }
    )

    with pytest.raises(TypeError):
        run_contrast(contrast, adapter)  # type: ignore[call-arg]


def test_probe_response_exposes_r1_score_metadata() -> None:
    response = ProbeResponse(
        model_id="fake-model-v1",
        requirement_id="contradiction_resolution",
        action_type="cross_check",
        content="structured output",
        input_tokens=3,
        output_tokens=2,
        evidence_score=0.75,
        scoring_issues=("one optional fact was omitted",),
    )

    assert response.evidence_score == 0.75
    assert response.scoring_issues == ("one optional fact was omitted",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", ""),
        ("requirement_id", ""),
        ("action_type", ""),
        ("input_tokens", -1),
        ("output_tokens", -1),
    ],
)
def test_probe_response_rejects_invalid_structured_metadata(
    field: str,
    value: str | int,
) -> None:
    values: dict[str, str | int] = {
        "model_id": "fake-model-v1",
        "requirement_id": "evidence",
        "action_type": "search",
        "content": "structured output",
        "input_tokens": 3,
        "output_tokens": 2,
    }
    values[field] = value

    with pytest.raises(ValueError):
        ProbeResponse(**values)  # type: ignore[arg-type]
