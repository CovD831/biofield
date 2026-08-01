from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class ProbeArm:
    """One fully identified arm of an A0 causal contrast.

    Fields hold immutable asset identifiers rather than prompt text so a run can
    record exact prompt, input, history, and task versions separately.
    """

    run_id: str
    system_prompt_id: str
    input_id: str
    history_id: str
    agent_label: str
    task_id: str
    role_induction: str
    clear_history: bool
    sample_id: int

    def __post_init__(self) -> None:
        identifiers = (
            self.run_id,
            self.system_prompt_id,
            self.input_id,
            self.history_id,
            self.agent_label,
            self.task_id,
            self.role_induction,
        )
        if any(not value for value in identifiers):
            raise ValueError("probe identifiers must be non-empty")
        if self.sample_id < 0:
            raise ValueError("sample_id cannot be negative")
        if self.clear_history and self.history_id != "history.empty.v1":
            raise ValueError("clear_history requires the empty history asset")

    @classmethod
    def reference(cls) -> ProbeArm:
        return cls(
            run_id="a0.reference",
            system_prompt_id="prompt.common.v1",
            input_id="input.common.v1",
            history_id="history.common.v1",
            agent_label="agent.a",
            task_id="software_release_readiness",
            role_induction="history",
            clear_history=False,
            sample_id=0,
        )


@dataclass(frozen=True)
class ProbeContrast:
    contrast_id: str
    causal_factor: str
    control: ProbeArm
    treatment: ProbeArm
    expected_changed_fields: frozenset[str]

    def changed_fields(self) -> frozenset[str]:
        ignored = {"run_id"}
        return frozenset(
            field.name
            for field in fields(ProbeArm)
            if field.name not in ignored
            and getattr(self.control, field.name) != getattr(self.treatment, field.name)
        )


def _contrast(
    base: ProbeArm,
    contrast_id: str,
    causal_factor: str,
    expected: set[str],
    control_changes: dict[str, object] | None = None,
    **treatment_changes: object,
) -> ProbeContrast:
    control = replace(
        base,
        run_id=f"a0.{contrast_id}.control",
        **(control_changes or {}),
    )
    treatment = replace(
        base,
        run_id=f"a0.{contrast_id}.treatment",
        **treatment_changes,
    )
    contrast = ProbeContrast(
        contrast_id=contrast_id,
        causal_factor=causal_factor,
        control=control,
        treatment=treatment,
        expected_changed_fields=frozenset(expected),
    )
    if contrast.changed_fields() != contrast.expected_changed_fields:
        raise ValueError(f"contrast {contrast_id} changes undeclared fields")
    return contrast


def build_a0_contrasts(base: ProbeArm) -> tuple[ProbeContrast, ...]:
    """Build the frozen eight-contrast A0 design without invoking a model."""

    return (
        _contrast(
            base,
            "sampling_noise",
            "sampling",
            {"sample_id"},
            sample_id=1,
        ),
        _contrast(
            base,
            "task_input",
            "input",
            {"input_id"},
            input_id="input.changed.v1",
        ),
        _contrast(
            base,
            "execution_history",
            "history",
            {"history_id"},
            history_id="history.specialized.v1",
        ),
        _contrast(
            base,
            "system_prompt",
            "system_prompt",
            {"system_prompt_id"},
            system_prompt_id="prompt.role.v1",
        ),
        _contrast(
            base,
            "agent_label",
            "label",
            {"agent_label"},
            agent_label="agent.b",
        ),
        _contrast(
            base,
            "task_identity",
            "task",
            {"task_id"},
            task_id="cold_chain_readiness",
        ),
        _contrast(
            base,
            "history_clear",
            "history",
            {"history_id", "clear_history"},
            history_id="history.empty.v1",
            clear_history=True,
        ),
        _contrast(
            base,
            "role_induction",
            "role_induction",
            {"history_id", "role_induction"},
            control_changes={"history_id": "history.specialized.v1"},
            role_induction="manual_prompt",
        ),
    )
