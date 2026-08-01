from __future__ import annotations

from biofield.model_probe import ProbeArm, build_a0_contrasts


def test_a0_matrix_contains_the_eight_declared_causal_contrasts() -> None:
    contrasts = build_a0_contrasts(ProbeArm.reference())

    assert [contrast.contrast_id for contrast in contrasts] == [
        "sampling_noise",
        "task_input",
        "execution_history",
        "system_prompt",
        "agent_label",
        "task_identity",
        "history_clear",
        "role_induction",
    ]


def test_each_a0_contrast_changes_only_its_declared_fields() -> None:
    contrasts = build_a0_contrasts(ProbeArm.reference())

    for contrast in contrasts:
        assert contrast.changed_fields() == contrast.expected_changed_fields


def test_a0_matrix_is_reproducible_and_has_distinct_run_ids() -> None:
    first = build_a0_contrasts(ProbeArm.reference())
    second = build_a0_contrasts(ProbeArm.reference())

    assert first == second
    run_ids = {
        run_id
        for contrast in first
        for run_id in (contrast.control.run_id, contrast.treatment.run_id)
    }
    assert len(run_ids) == 16


def test_role_induction_contrast_compares_history_with_manual_prompt() -> None:
    contrast = next(
        item
        for item in build_a0_contrasts(ProbeArm.reference())
        if item.contrast_id == "role_induction"
    )

    assert contrast.control.role_induction == "history"
    assert contrast.control.history_id == "history.specialized.v1"
    assert contrast.treatment.role_induction == "manual_prompt"
    assert contrast.treatment.history_id == "history.common.v1"
    assert contrast.expected_changed_fields == frozenset(
        {"history_id", "role_induction"}
    )
