from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol

from biofield.model_probe import ProbeArm, ProbeContrast

RunStatus = Literal["completed", "failed"]
PairCondition = Literal["control", "treatment"]
ExecutionOrder = Literal["control_first", "treatment_first"]
Clock = Callable[[], float]


@dataclass(frozen=True, order=True)
class BehaviorSignature:
    """Provider-independent action coordinates used by A0 comparisons."""

    requirement_id: str
    action_type: str

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.action_type:
            raise ValueError("behavior signature fields must be non-empty")


@dataclass(frozen=True)
class ModelInvocationAudit:
    """Provider-neutral audit fields for one concrete model invocation."""

    request_fingerprint: str
    provider_payload_hash: str
    provider_response_hash: str
    effective_seed: int
    provider_model_id: str
    done_reason: str
    total_duration_ns: int
    load_duration_ns: int
    prompt_eval_duration_ns: int
    eval_duration_ns: int

    def __post_init__(self) -> None:
        if not self.request_fingerprint or not self.provider_model_id:
            raise ValueError("audit identifiers must be non-empty")
        if not self.done_reason:
            raise ValueError("done_reason must be non-empty")
        for name in ("provider_payload_hash", "provider_response_hash"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        for name in (
            "effective_seed",
            "total_duration_ns",
            "load_duration_ns",
            "prompt_eval_duration_ns",
            "eval_duration_ns",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ProbeResponse:
    """One adapter-normalized model response.

    The adapter owns prompt asset resolution and provider parsing. The runner
    only consumes these stable fields, so no provider SDK type crosses the A0
    experiment boundary.
    """

    model_id: str
    requirement_id: str
    action_type: str
    content: str
    input_tokens: int | None
    output_tokens: int | None
    evidence_score: float | None = None
    critical_fact_score: float | None = None
    citation_score: float | None = None
    contradiction_score: float | None = None
    decision_score: float | None = None
    scoring_issues: tuple[str, ...] = ()
    audit: ModelInvocationAudit | None = None

    def __post_init__(self) -> None:
        identifiers = (self.model_id, self.requirement_id, self.action_type)
        if any(not isinstance(value, str) or not value for value in identifiers):
            raise ValueError("model and action identifiers must be non-empty strings")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        object.__setattr__(self, "scoring_issues", tuple(self.scoring_issues))
        for name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer or None")
        for name in (
            "evidence_score",
            "critical_fact_score",
            "citation_score",
            "contradiction_score",
            "decision_score",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"{name} must be between zero and one or None")
        if any(
            not isinstance(issue, str) or not issue.strip()
            for issue in self.scoring_issues
        ):
            raise ValueError("scoring_issues must contain non-empty strings")
        if self.audit is not None and not isinstance(
            self.audit,
            ModelInvocationAudit,
        ):
            raise ValueError("audit must be ModelInvocationAudit or None")

    @property
    def behavior_signature(self) -> BehaviorSignature:
        return BehaviorSignature(self.requirement_id, self.action_type)


class ModelAdapter(Protocol):
    """Minimal provider-neutral boundary required by the A0 runner."""

    def invoke(self, arm: ProbeArm) -> ProbeResponse:
        """Resolve an arm's assets and return normalized structured output."""

        ...


@dataclass(frozen=True)
class RunRecord:
    """Auditable outcome for one arm, including failures and measured latency."""

    pair_id: str
    contrast_id: str
    causal_factor: str
    condition: PairCondition
    arm: ProbeArm
    status: RunStatus
    latency_ms: float
    response: ProbeResponse | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if not self.pair_id or not self.contrast_id or not self.causal_factor:
            raise ValueError("run identifiers must be non-empty")
        if self.condition not in ("control", "treatment"):
            raise ValueError("condition must be control or treatment")
        if self.status not in ("completed", "failed"):
            raise ValueError("status must be completed or failed")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        if self.status == "completed":
            if not isinstance(self.response, ProbeResponse):
                raise ValueError("completed run requires a response")
            if self.failure_type is not None or self.failure_message is not None:
                raise ValueError("completed run cannot contain failure metadata")
        else:
            if self.response is not None:
                raise ValueError("failed run cannot contain a response")
            if not self.failure_type or not self.failure_message:
                raise ValueError("failed run requires explicit failure metadata")

    @property
    def behavior_signature(self) -> BehaviorSignature | None:
        return self.response.behavior_signature if self.response is not None else None

    @property
    def input_tokens(self) -> int | None:
        return self.response.input_tokens if self.response is not None else None

    @property
    def output_tokens(self) -> int | None:
        return self.response.output_tokens if self.response is not None else None

    @property
    def evidence_score(self) -> float | None:
        return self.response.evidence_score if self.response is not None else None


@dataclass(frozen=True)
class SamplingNoiseSignature:
    """Structured signature pair for an otherwise identical sampling contrast."""

    control: BehaviorSignature
    treatment: BehaviorSignature

    @property
    def changed(self) -> bool:
        return self.control != self.treatment


@dataclass(frozen=True)
class PairedRun:
    """Control and treatment records produced from one frozen contrast."""

    contrast: ProbeContrast
    control: RunRecord
    treatment: RunRecord
    pair_id: str
    pair_seed: int | None
    execution_order: ExecutionOrder

    def __post_init__(self) -> None:
        if not isinstance(self.pair_id, str) or not self.pair_id.strip():
            raise ValueError("pair_id must be a non-empty string")
        if self.pair_seed is not None and (
            isinstance(self.pair_seed, bool)
            or not isinstance(self.pair_seed, int)
            or self.pair_seed < 0
        ):
            raise ValueError("pair_seed must be a non-negative integer or None")
        if self.execution_order not in ("control_first", "treatment_first"):
            raise ValueError("invalid paired execution order")
        expected = (
            (self.control, "control", self.contrast.control),
            (self.treatment, "treatment", self.contrast.treatment),
        )
        for record, condition, arm in expected:
            if record.condition != condition:
                raise ValueError("paired record condition mismatch")
            if record.arm != arm:
                raise ValueError("paired record arm mismatch")
            if record.pair_id != self.pair_id:
                raise ValueError("paired record pair_id mismatch")
            if record.contrast_id != self.contrast.contrast_id:
                raise ValueError("paired record contrast_id mismatch")
            if record.causal_factor != self.contrast.causal_factor:
                raise ValueError("paired record causal factor mismatch")

    @property
    def records(self) -> tuple[RunRecord, RunRecord]:
        return (self.control, self.treatment)

    @property
    def sampling_noise_signature(self) -> SamplingNoiseSignature | None:
        is_same_condition_sampling = (
            self.contrast.causal_factor == "sampling"
            and self.contrast.changed_fields() == frozenset({"sample_id"})
        )
        if not is_same_condition_sampling:
            return None
        control = self.control.behavior_signature
        treatment = self.treatment.behavior_signature
        if control is None or treatment is None:
            return None
        return SamplingNoiseSignature(control=control, treatment=treatment)


def _elapsed_ms(start: float, end: float) -> float:
    elapsed = (end - start) * 1_000.0
    if not math.isfinite(elapsed):
        raise ValueError("clock produced a non-finite duration")
    return max(0.0, elapsed)


def _run_arm(
    contrast: ProbeContrast,
    pair_id: str,
    condition: PairCondition,
    arm: ProbeArm,
    adapter: ModelAdapter,
    clock: Clock,
) -> RunRecord:
    start = clock()
    try:
        response = adapter.invoke(arm)
        if not isinstance(response, ProbeResponse):
            raise TypeError("adapter must return ProbeResponse")
    except Exception as error:
        return RunRecord(
            pair_id=pair_id,
            contrast_id=contrast.contrast_id,
            causal_factor=contrast.causal_factor,
            condition=condition,
            arm=arm,
            status="failed",
            latency_ms=_elapsed_ms(start, clock()),
            failure_type=type(error).__name__,
            failure_message=str(error) or "<no failure message>",
        )
    return RunRecord(
        pair_id=pair_id,
        contrast_id=contrast.contrast_id,
        causal_factor=contrast.causal_factor,
        condition=condition,
        arm=arm,
        status="completed",
        latency_ms=_elapsed_ms(start, clock()),
        response=response,
    )


def run_contrast(
    contrast: ProbeContrast,
    adapter: ModelAdapter,
    *,
    pair_id: str | None = None,
    pair_seed: int | None = None,
    execution_order: ExecutionOrder,
    clock: Clock = perf_counter,
) -> PairedRun:
    """Execute both arms in an explicit counterbalanced order."""

    resolved_pair_id = contrast.contrast_id if pair_id is None else pair_id
    if not isinstance(resolved_pair_id, str) or not resolved_pair_id.strip():
        raise ValueError("pair_id must be a non-empty string")
    if pair_seed is not None and (
        isinstance(pair_seed, bool)
        or not isinstance(pair_seed, int)
        or pair_seed < 0
    ):
        raise ValueError("pair_seed must be a non-negative integer or None")
    if execution_order == "control_first":
        control = _run_arm(
            contrast,
            resolved_pair_id,
            "control",
            contrast.control,
            adapter,
            clock,
        )
        treatment = _run_arm(
            contrast,
            resolved_pair_id,
            "treatment",
            contrast.treatment,
            adapter,
            clock,
        )
    elif execution_order == "treatment_first":
        treatment = _run_arm(
            contrast,
            resolved_pair_id,
            "treatment",
            contrast.treatment,
            adapter,
            clock,
        )
        control = _run_arm(
            contrast,
            resolved_pair_id,
            "control",
            contrast.control,
            adapter,
            clock,
        )
    else:
        raise ValueError("execution_order must be control_first or treatment_first")
    return PairedRun(
        contrast=contrast,
        control=control,
        treatment=treatment,
        pair_id=resolved_pair_id,
        pair_seed=pair_seed,
        execution_order=execution_order,
    )
