from __future__ import annotations

import re
from dataclasses import dataclass, replace

from biofield.a0_runner import ExecutionOrder
from biofield.model_probe import ProbeArm, ProbeContrast, build_a0_contrasts

CORE_CONTRAST_IDS = (
    "sampling_noise",
    "execution_history",
    "history_clear",
    "role_induction",
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class A0ScheduledPair:
    pair_id: str
    contrast_id: str
    task_id: str
    agent_label: str
    repeat_index: int
    primary_seed: int
    alternate_seed: int
    execution_order: ExecutionOrder
    contrast: ProbeContrast

    def __post_init__(self) -> None:
        if not self.pair_id or self.contrast_id not in CORE_CONTRAST_IDS:
            raise ValueError("invalid scheduled pair identity")
        if self.contrast.contrast_id != self.contrast_id:
            raise ValueError("scheduled contrast identity mismatch")
        if self.repeat_index <= 0:
            raise ValueError("repeat_index must be positive")
        if self.primary_seed < 0 or self.alternate_seed < 0:
            raise ValueError("scheduled seeds must be non-negative")
        if self.primary_seed == self.alternate_seed:
            raise ValueError("primary and alternate seeds must differ")
        if self.execution_order not in ("control_first", "treatment_first"):
            raise ValueError("invalid execution order")

    @property
    def control_seed(self) -> int:
        return self.primary_seed

    @property
    def treatment_seed(self) -> int:
        if self.contrast_id == "sampling_noise":
            return self.alternate_seed
        return self.primary_seed


def _validate_identifiers(values: tuple[str, ...], field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} cannot be empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must be unique")
    if any(
        not isinstance(value, str)
        or not value
        or _SAFE_IDENTIFIER.fullmatch(value) is None
        for value in values
    ):
        raise ValueError(f"{field_name} contain an unsafe identifier")


def build_core_schedule(
    *,
    task_ids: tuple[str, ...],
    agent_labels: tuple[str, ...],
    repeats: int,
    base_seed: int,
    seed_stride: int = 100,
) -> tuple[A0ScheduledPair, ...]:
    """Freeze the four-condition A0 order and blocked seed assignment."""

    _validate_identifiers(task_ids, "task_ids")
    _validate_identifiers(agent_labels, "agent_labels")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats <= 0:
        raise ValueError("repeats must be a positive integer")
    if (
        isinstance(base_seed, bool)
        or not isinstance(base_seed, int)
        or base_seed < 0
    ):
        raise ValueError("base_seed must be a non-negative integer")
    if (
        isinstance(seed_stride, bool)
        or not isinstance(seed_stride, int)
        or seed_stride < 2
    ):
        raise ValueError("seed_stride must be an integer of at least two")

    schedule: list[A0ScheduledPair] = []
    agent_count = len(agent_labels)
    task_count = len(task_ids)
    reference_contrasts = {
        item.contrast_id: item
        for item in build_a0_contrasts(ProbeArm.reference())
        if item.contrast_id in CORE_CONTRAST_IDS
    }
    for repeat_offset in range(repeats):
        repeat_index = repeat_offset + 1
        for task_index, task_id in enumerate(task_ids):
            for agent_index, agent_label in enumerate(agent_labels):
                block_index = (
                    repeat_offset * task_count * agent_count
                    + task_index * agent_count
                    + agent_index
                )
                primary_seed = base_seed + block_index * seed_stride
                alternate_seed = primary_seed + 1
                for contrast_index, contrast_id in enumerate(CORE_CONTRAST_IDS):
                    template = reference_contrasts[contrast_id]
                    pair_id = (
                        f"a0.{contrast_id}.{task_id}.{agent_label}."
                        f"rep{repeat_index:02d}"
                    )
                    contrast = replace(
                        template,
                        control=replace(
                            template.control,
                            run_id=f"{pair_id}.control",
                            task_id=task_id,
                            agent_label=agent_label,
                        ),
                        treatment=replace(
                            template.treatment,
                            run_id=f"{pair_id}.treatment",
                            task_id=task_id,
                            agent_label=agent_label,
                        ),
                    )
                    starts_control = (
                        task_index * agent_count + agent_index + contrast_index
                    ) % 2 == 0
                    control_first = starts_control == (repeat_offset % 2 == 0)
                    execution_order: ExecutionOrder = (
                        "control_first" if control_first else "treatment_first"
                    )
                    schedule.append(
                        A0ScheduledPair(
                            pair_id=pair_id,
                            contrast_id=contrast_id,
                            task_id=task_id,
                            agent_label=agent_label,
                            repeat_index=repeat_index,
                            primary_seed=primary_seed,
                            alternate_seed=alternate_seed,
                            execution_order=execution_order,
                            contrast=contrast,
                        )
                    )
    return tuple(schedule)
