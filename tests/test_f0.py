from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from biofield.contracts import RequirementStatus, RunTerminalStatus
from biofield.evidence_task import load_task_bundle
from biofield.f0 import (
    DeterministicF0Executor,
    F0Experiment,
    F0RunConfig,
    RunAlreadyTerminal,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _experiment(
    tmp_path: Path,
    *,
    action_budget: int = 3,
    max_cycles: int = 5,
    fail_on: str | None = None,
    invalid_on: str | None = None,
) -> F0Experiment:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    return F0Experiment(
        bundle=bundle,
        executor=DeterministicF0Executor(
            bundle,
            fail_on_requirement=fail_on,
            invalid_on_requirement=invalid_on,
        ),
        config=F0RunConfig(
            output_directory=tmp_path / "runs",
            run_id="contract",
            action_budget=action_budget,
            max_cycles=max_cycles,
        ),
    )


def test_f0_contract_runs_action_feedback_reallocation_and_settlement(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)

    result = experiment.run()

    assert result.status is RunTerminalStatus.COMPLETED
    assert result.cycles == 3
    assert result.residual.complete is True
    assert [item.requirement_id for item in result.allocations] == [
        "fact_extraction",
        "contradiction_resolution",
        "decision_synthesis",
    ]
    assert [item.agent_id for item in result.allocations] == [
        "agent.fact",
        "agent.conflict",
        "agent.decision",
    ]
    assert [item.residual_revision for item in result.allocations] == [0, 1, 2]
    assert len(result.actions) == 3
    assert [item.input_refs for item in result.actions] == [
        (),
        ("artifacts/action-000.json",),
        ("artifacts/action-000.json", "artifacts/action-001.json"),
    ]
    assert len(result.feedback) == 3
    assert all(item.evidence_refs for item in result.feedback)
    assert result.ledger_totals["action_units"].spent == Decimal("3")
    assert result.ledger_totals["action_units"].accounted == Decimal("3")
    assert result.ledger_totals["action_units"].expected == Decimal("3")

    run_directory = tmp_path / "runs" / "f0-contract" / "contract"
    assert (run_directory / "finalization.json").exists()
    assert (run_directory / "metrics.json").exists()
    assert (run_directory / "summary.md").exists()

    with pytest.raises(RunAlreadyTerminal, match="terminal"):
        experiment.run()


def test_action_failure_is_terminal_without_completing_downstream_work(
    tmp_path: Path,
) -> None:
    result = _experiment(
        tmp_path,
        fail_on="contradiction_resolution",
    ).run()

    assert result.status is RunTerminalStatus.FAILED
    assert result.cycles == 2
    assert result.residual.requirement("fact_extraction").status is RequirementStatus.SATISFIED
    assert result.residual.requirement("contradiction_resolution").status is RequirementStatus.UNMET
    assert result.residual.requirement("decision_synthesis").status is RequirementStatus.UNMET
    assert result.residual.complete is False
    assert result.ledger_totals["action_units"].spent == Decimal("2")
    assert [item.requirement_id for item in result.allocations] == [
        "fact_extraction",
        "contradiction_resolution",
    ]


def test_invalid_evidence_is_rejected_and_cannot_claim_completion(
    tmp_path: Path,
) -> None:
    result = _experiment(
        tmp_path,
        action_budget=2,
        max_cycles=2,
        invalid_on="fact_extraction",
    ).run()

    assert result.status is RunTerminalStatus.MAX_CYCLES
    assert result.residual.complete is False
    assert result.residual.requirement("fact_extraction").status is RequirementStatus.UNMET
    assert all(
        delta.disposition.value == "rejected"
        for feedback in result.feedback
        for delta in feedback.requirement_deltas
    )
    assert result.ledger_totals["action_units"].spent == Decimal("2")


def test_insufficient_budget_terminates_before_unfunded_action(tmp_path: Path) -> None:
    result = _experiment(tmp_path, action_budget=1).run()

    assert result.status is RunTerminalStatus.BUDGET_EXHAUSTED
    assert result.cycles == 1
    assert len(result.actions) == 1
    assert result.residual.requirement("fact_extraction").status is RequirementStatus.SATISFIED
    assert result.residual.requirement("contradiction_resolution").status is RequirementStatus.UNMET
    assert result.ledger_totals["action_units"].spent == Decimal("1")
    assert result.ledger_totals["action_units"].shared_pool == Decimal("0")
