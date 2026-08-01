from __future__ import annotations

from biofield.meas0 import Meas0Arm
from biofield.meas0_pilot_runner import CostVector, RunValidity
from biofield.meas0_readiness import (
    BudgetPolicy,
    TaskBudgetLimit,
)
from biofield.meas0_budget import (
    BudgetEnforcer,
    BudgetFailureCode,
    BudgetScope,
)
from biofield.measurement import EvaluationStatus


def _policy() -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="meas0-budget-v1",
        version=1,
        task_limits=(
            TaskBudgetLimit(
                task_id="cold_chain_readiness",
                deterministic_checks=24,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=8192,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=60_000,
                judge_wall_time_ms=120_000,
            ),
            TaskBudgetLimit(
                task_id="channel_order_ingest",
                deterministic_checks=32,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=16_384,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=180_000,
                judge_wall_time_ms=120_000,
            ),
        ),
        pilot_judge_calls=240,
        pilot_human_escalations=8,
        exhaustion_status=EvaluationStatus.UNKNOWN,
        retain_exhausted_cases=True,
    )


def test_budget_enforcer_retains_per_arm_case_as_unknown_on_limit() -> None:
    enforcer = BudgetEnforcer(_policy())
    disposition = enforcer.enforce(
        case_id="case-01",
        task_id="cold_chain_readiness",
        arm=Meas0Arm.STATE_ONLY,
        run_validity=RunValidity.VALID,
        automatic_status=EvaluationStatus.PASS,
        cost=CostVector(deterministic_check_calls=25),
    )

    assert disposition.run_validity is RunValidity.VALID
    assert disposition.automatic_status is EvaluationStatus.UNKNOWN
    assert disposition.retained_in_denominator is True
    assert disposition.failure is not None
    assert disposition.failure.code is BudgetFailureCode.BUDGET_EXHAUSTED
    assert disposition.failure.scope is BudgetScope.ARM_CASE
    assert disposition.failure.metric == "deterministic_check_calls"
    assert disposition.failure.limit == 24
    assert disposition.failure.observed == 25


def test_stage_budget_is_consumed_once_and_never_grants_an_arm_retry() -> None:
    enforcer = BudgetEnforcer(_policy())
    for index in range(120):
        allowed = enforcer.enforce(
            case_id=f"case-{index:03d}",
            task_id="cold_chain_readiness",
            arm=Meas0Arm.JUDGE_ONLY,
            run_validity=RunValidity.VALID,
            automatic_status=EvaluationStatus.PASS,
            cost=CostVector(judge_calls=2),
        )
        assert allowed.failure is None

    exhausted = enforcer.enforce(
        case_id="case-121",
        task_id="cold_chain_readiness",
        arm=Meas0Arm.JUDGE_ONLY,
        run_validity=RunValidity.VALID,
        automatic_status=EvaluationStatus.PASS,
        cost=CostVector(judge_calls=1),
    )
    assert exhausted.automatic_status is EvaluationStatus.UNKNOWN
    assert exhausted.failure is not None
    assert exhausted.failure.scope is BudgetScope.STAGE
    assert exhausted.failure.observed == 241
    assert enforcer.stage_cost.judge_calls == 241

    duplicate = enforcer.enforce(
        case_id="case-121",
        task_id="cold_chain_readiness",
        arm=Meas0Arm.JUDGE_ONLY,
        run_validity=RunValidity.VALID,
        automatic_status=EvaluationStatus.PASS,
        cost=CostVector(judge_calls=0),
    )
    assert duplicate.run_validity is RunValidity.INVALID
    assert duplicate.automatic_status is None
    assert duplicate.failure is not None
    assert duplicate.failure.code is BudgetFailureCode.ACCOUNTING_INVALID
