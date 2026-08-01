from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.measurement import EvaluationStatus
from biofield.meas0_judge_probes import (
    JudgeProbeCall,
    JudgeProbeContractError,
    JudgeProbeManifest,
    JudgeProbeRelation,
    ProbeKind,
    derive_probe_rates,
)


def _hash(character: str) -> str:
    return character * 64


def _manifest() -> JudgeProbeManifest:
    calls = []
    relations = []
    for index in range(48):
        item_id = f"item-{index:02d}"
        specs = (
            ("order-base", _hash("a")),
            ("order-reversed", _hash("b")),
            ("style-base", _hash("c")),
            ("style-variant", _hash("d")),
            ("repeat-a", _hash("e")),
            ("repeat-b", _hash("e")),
        )
        for offset, (presentation, presentation_hash) in enumerate(specs):
            calls.append(
                JudgeProbeCall(
                    call_id=f"{item_id}.{presentation}",
                    item_id=item_id,
                    presentation=presentation,
                    presentation_hash=presentation_hash,
                    schedule_id=f"schedule-{index:02d}-{offset}",
                )
            )
        for kind, left, right in (
            (ProbeKind.ORDER, "order-base", "order-reversed"),
            (ProbeKind.STYLE, "style-base", "style-variant"),
            (ProbeKind.REPEAT, "repeat-a", "repeat-b"),
        ):
            relations.append(
                JudgeProbeRelation(
                    relation_id=f"{item_id}.{kind.value}",
                    item_id=item_id,
                    kind=kind,
                    left_call_id=f"{item_id}.{left}",
                    right_call_id=f"{item_id}.{right}",
                )
            )
    return JudgeProbeManifest(
        manifest_id="J-CAL-PROBES-v2",
        version=2,
        judge_set_hash=_hash("f"),
        protected_corpus_hash=_hash("0"),
        calls=tuple(calls),
        relations=tuple(relations),
        test_only=True,
    )


def test_probe_manifest_registers_three_non_reused_relations_per_item() -> None:
    manifest = _manifest()

    assert len(manifest.calls) == 48 * 6
    assert len(manifest.relations) == 48 * 3
    assert manifest.item_ids == tuple(f"item-{index:02d}" for index in range(48))
    assert manifest.production_ready is False

    verdicts = {call.call_id: EvaluationStatus.PASS for call in manifest.calls}
    rates = derive_probe_rates(manifest, verdicts)
    assert rates.order_flip.value == 0.0
    assert rates.style_flip.value == 0.0
    assert rates.repeat_disagreement.value == 0.0
    assert rates.order_flip.denominator == 48


def test_probe_rates_are_independent_and_missing_calls_fail_closed() -> None:
    manifest = _manifest()
    verdicts = {call.call_id: EvaluationStatus.PASS for call in manifest.calls}
    verdicts["item-00.style-variant"] = EvaluationStatus.FAIL

    rates = derive_probe_rates(manifest, verdicts)
    assert rates.order_flip.value == 0.0
    assert rates.style_flip.value == pytest.approx(1 / 48)
    assert rates.repeat_disagreement.value == 0.0

    del verdicts["item-01.repeat-b"]
    with pytest.raises(JudgeProbeContractError, match="exactly match"):
        derive_probe_rates(manifest, verdicts)


def test_probe_manifest_rejects_pair_reuse_and_nonidentical_repeat() -> None:
    manifest = _manifest()
    reused = replace(
        manifest.relations[1],
        left_call_id=manifest.relations[0].left_call_id,
        right_call_id=manifest.relations[0].right_call_id,
    )
    with pytest.raises(JudgeProbeContractError, match="call pair"):
        replace(
            manifest, relations=(manifest.relations[0], reused) + manifest.relations[2:]
        )

    calls = list(manifest.calls)
    calls[5] = replace(calls[5], presentation_hash=_hash("9"))
    with pytest.raises(JudgeProbeContractError, match="identical presentation"):
        replace(manifest, calls=tuple(calls))
