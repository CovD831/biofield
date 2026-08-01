from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from biofield.contracts import RunTerminalStatus
from biofield.evidence_task import load_task_bundle
from biofield.f0 import F0Experiment, F0RunConfig
from biofield.f0_model import InjectInvalidFirstExecutor, OllamaF0Executor


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


@dataclass(frozen=True)
class FakeInvocation:
    structured_output: Mapping[str, Any]
    input_tokens: int
    output_tokens: int
    audit: Any


class QueueAdapter:
    model_id = "qwen3:8b"

    def __init__(self, outputs: list[Mapping[str, Any]]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def invoke_structured(self, **kwargs: Any) -> FakeInvocation:
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        call_number = len(self.calls)
        return FakeInvocation(
            structured_output=output,
            input_tokens=100 * call_number,
            output_tokens=10 * call_number,
            audit=SimpleNamespace(total_duration_ns=1_000_000 * call_number),
        )


def _perfect_role_outputs(bundle: Any) -> list[Mapping[str, Any]]:
    return [
        {
            "key_facts": [
                {
                    "fact_id": fact.fact_id,
                    "value": fact.accepted_values[0],
                    "citations": list(
                        fact.supporting_material_ids[: fact.minimum_citations]
                    ),
                }
                for fact in bundle.answer_key.key_facts
            ]
        },
        {
            "contradictions": [
                {
                    "contradiction_id": item.contradiction_id,
                    "material_ids": list(item.material_ids),
                }
                for item in bundle.answer_key.contradictions
            ]
        },
        {"decision": bundle.answer_key.decision},
    ]


def test_model_executor_uses_role_schemas_real_history_and_token_ledger(
    tmp_path: Path,
) -> None:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    adapter = QueueAdapter(_perfect_role_outputs(bundle))
    executor = OllamaF0Executor(
        bundle=bundle,
        adapter=adapter,
        base_seed=9000,
        token_reservation=1000,
    )

    result = F0Experiment(
        bundle=bundle,
        executor=executor,
        config=F0RunConfig(
            output_directory=tmp_path / "runs",
            run_id="model",
            action_budget=3,
            token_budget=5000,
            max_cycles=3,
        ),
    ).run()

    assert result.status is RunTerminalStatus.COMPLETED
    assert len(adapter.calls) == 3
    assert [call["effective_seed"] for call in adapter.calls] == [9000, 9001, 9002]
    assert [set(call["response_schema"]["required"]) for call in adapter.calls] == [
        {"key_facts"},
        {"contradictions"},
        {"decision"},
    ]
    fact_items = adapter.calls[0]["response_schema"]["properties"]["key_facts"]
    assert fact_items["minItems"] == len(bundle.answer_key.key_facts)
    assert fact_items["items"]["properties"]["fact_id"]["enum"] == [
        item.fact_id for item in bundle.answer_key.key_facts
    ]
    assert "oneOf" not in fact_items["items"]
    assert "prior verified artifacts: {}" in adapter.calls[0]["messages"][0]["content"]
    assert '"minimum_citations"' in adapter.calls[0]["messages"][0]["content"]
    assert '"generator_test": {"enum": ["passed", "failed", "unknown"]' in adapter.calls[0]["messages"][0]["content"]
    assert "key_facts" in adapter.calls[1]["messages"][0]["content"]
    assert "contradictions" in adapter.calls[2]["messages"][0]["content"]

    # Calls consumed (100+10) + (200+20) + (300+30) tokens.
    assert result.ledger_totals["tokens"].spent == Decimal("660")
    assert result.ledger_totals["tokens"].shared_pool == Decimal("4340")
    assert result.ledger_totals["tokens"].accounted == Decimal("5000")
    assert result.ledger_totals["tokens"].expected == Decimal("5000")
    model_events = [
        event
        for event in (result.run_directory / "events.jsonl").read_text().splitlines()
        if '"event_type":"model_invocation"' in event
    ]
    assert len(model_events) == 3


def test_rejected_first_evidence_is_reallocated_and_then_recovers(tmp_path: Path) -> None:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    adapter = QueueAdapter(_perfect_role_outputs(bundle))
    model_executor = OllamaF0Executor(
        bundle=bundle,
        adapter=adapter,
        base_seed=9100,
        token_reservation=1000,
    )

    result = F0Experiment(
        bundle=bundle,
        executor=InjectInvalidFirstExecutor(model_executor),
        config=F0RunConfig(
            output_directory=tmp_path / "runs",
            run_id="recover",
            action_budget=4,
            token_budget=5000,
            max_cycles=4,
        ),
    ).run()

    assert result.status is RunTerminalStatus.COMPLETED
    assert [item.requirement_id for item in result.allocations] == [
        "fact_extraction",
        "fact_extraction",
        "contradiction_resolution",
        "decision_synthesis",
    ]
    assert [
        delta.disposition.value
        for feedback in result.feedback
        for delta in feedback.requirement_deltas
    ] == ["rejected", "accepted", "accepted", "accepted"]
    assert result.feedback[1].requirement_deltas[0].invalidates_feedback_ids == (
        "feedback-000",
    )
    assert len(adapter.calls) == 3
    assert result.ledger_totals["action_units"].spent == Decimal("4")
    assert result.ledger_totals["tokens"].spent == Decimal("660")
