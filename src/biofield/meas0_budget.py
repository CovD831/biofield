"""Deterministic MEAS0 budget accounting and fail-closed dispositions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .meas0 import Meas0Arm
from .meas0_pilot_runner import CostVector, PilotRunnerError, RunValidity
from .meas0_readiness import BudgetPolicy, TaskBudgetLimit
from .measurement import EvaluationStatus


class BudgetFailureCode(str, Enum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    ACCOUNTING_INVALID = "accounting_invalid"


class BudgetScope(str, Enum):
    ARM_CASE = "arm_case"
    STAGE = "stage"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class BudgetFailureArtifact:
    case_id: str
    task_id: str
    arm: Meas0Arm
    code: BudgetFailureCode
    scope: BudgetScope
    metric: str
    limit: int
    observed: int
    retained_in_denominator: bool = True

    def __post_init__(self) -> None:
        if (
            not self.case_id
            or not self.task_id
            or not isinstance(self.arm, Meas0Arm)
            or not isinstance(self.code, BudgetFailureCode)
            or not isinstance(self.scope, BudgetScope)
            or not self.metric
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (self.limit, self.observed)
            )
            or self.retained_in_denominator is not True
        ):
            raise PilotRunnerError("budget failure artifact is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "task_id": self.task_id,
            "arm": self.arm.value,
            "code": self.code.value,
            "scope": self.scope.value,
            "metric": self.metric,
            "limit": self.limit,
            "observed": self.observed,
            "retained_in_denominator": self.retained_in_denominator,
        }


@dataclass(frozen=True)
class BudgetDisposition:
    case_id: str
    task_id: str
    arm: Meas0Arm
    run_validity: RunValidity
    automatic_status: EvaluationStatus | None
    original_run_validity: RunValidity
    original_automatic_status: EvaluationStatus | None
    cost: CostVector
    failure: BudgetFailureArtifact | None
    retained_in_denominator: bool = True

    def __post_init__(self) -> None:
        if self.run_validity is RunValidity.INVALID:
            if self.automatic_status is not None:
                raise PilotRunnerError(
                    "invalid budget disposition must have null status"
                )
        elif self.automatic_status is None:
            raise PilotRunnerError("valid budget disposition requires status")
        if self.retained_in_denominator is not True:
            raise PilotRunnerError("budget disposition cannot drop a case")

    @property
    def disposition_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def _body(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "task_id": self.task_id,
            "arm": self.arm.value,
            "run_validity": self.run_validity.value,
            "automatic_status": (
                self.automatic_status.value
                if self.automatic_status is not None
                else None
            ),
            "original_run_validity": self.original_run_validity.value,
            "original_automatic_status": (
                self.original_automatic_status.value
                if self.original_automatic_status is not None
                else None
            ),
            "cost": self.cost.to_dict(),
            "failure": self.failure.to_dict() if self.failure is not None else None,
            "retained_in_denominator": self.retained_in_denominator,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "disposition_hash": self.disposition_hash}


def _add_cost(left: CostVector, right: CostVector) -> CostVector:
    return CostVector(
        **{
            field_name: getattr(left, field_name) + getattr(right, field_name)
            for field_name in left.__dataclass_fields__
        }
    )


class BudgetEnforcer:
    """Single-use per arm-case accounting against one frozen pilot policy."""

    def __init__(self, policy: BudgetPolicy) -> None:
        if not isinstance(policy, BudgetPolicy):
            raise PilotRunnerError("BudgetEnforcer requires a BudgetPolicy")
        self.policy = policy
        self._limits = {item.task_id: item for item in policy.task_limits}
        self._seen: set[tuple[str, Meas0Arm]] = set()
        self._stage_cost = CostVector()

    @property
    def stage_cost(self) -> CostVector:
        return self._stage_cost

    def enforce(
        self,
        *,
        case_id: str,
        task_id: str,
        arm: Meas0Arm,
        run_validity: RunValidity,
        automatic_status: EvaluationStatus | None,
        cost: CostVector,
    ) -> BudgetDisposition:
        selected_arm = arm if isinstance(arm, Meas0Arm) else Meas0Arm(arm)
        key = (case_id, selected_arm)
        if key in self._seen or task_id not in self._limits:
            return self._invalid(
                case_id=case_id,
                task_id=task_id,
                arm=selected_arm,
                run_validity=run_validity,
                automatic_status=automatic_status,
                cost=cost,
                metric="arm_case_accounting",
            )
        self._seen.add(key)
        self._stage_cost = _add_cost(self._stage_cost, cost)
        limit = self._limits[task_id]
        violation = self._arm_case_violation(
            arm=selected_arm,
            cost=cost,
            limit=limit,
        )
        if violation is None:
            violation = self._stage_violation()
        if violation is None:
            return BudgetDisposition(
                case_id=case_id,
                task_id=task_id,
                arm=selected_arm,
                run_validity=run_validity,
                automatic_status=automatic_status,
                original_run_validity=run_validity,
                original_automatic_status=automatic_status,
                cost=cost,
                failure=None,
            )
        scope, metric, maximum, observed = violation
        failure = BudgetFailureArtifact(
            case_id=case_id,
            task_id=task_id,
            arm=selected_arm,
            code=BudgetFailureCode.BUDGET_EXHAUSTED,
            scope=scope,
            metric=metric,
            limit=maximum,
            observed=observed,
        )
        return BudgetDisposition(
            case_id=case_id,
            task_id=task_id,
            arm=selected_arm,
            run_validity=RunValidity.VALID,
            automatic_status=self.policy.exhaustion_status,
            original_run_validity=run_validity,
            original_automatic_status=automatic_status,
            cost=cost,
            failure=failure,
        )

    def _invalid(
        self,
        *,
        case_id: str,
        task_id: str,
        arm: Meas0Arm,
        run_validity: RunValidity,
        automatic_status: EvaluationStatus | None,
        cost: CostVector,
        metric: str,
    ) -> BudgetDisposition:
        failure = BudgetFailureArtifact(
            case_id=case_id,
            task_id=task_id,
            arm=arm,
            code=BudgetFailureCode.ACCOUNTING_INVALID,
            scope=BudgetScope.ARM_CASE,
            metric=metric,
            limit=1,
            observed=2,
        )
        return BudgetDisposition(
            case_id=case_id,
            task_id=task_id,
            arm=arm,
            run_validity=RunValidity.INVALID,
            automatic_status=None,
            original_run_validity=run_validity,
            original_automatic_status=automatic_status,
            cost=cost,
            failure=failure,
        )

    @staticmethod
    def _arm_case_violation(
        *,
        arm: Meas0Arm,
        cost: CostVector,
        limit: TaskBudgetLimit,
    ) -> tuple[BudgetScope, str, int, int] | None:
        checks: list[tuple[str, int, int]] = [
            ("human_escalations", limit.human_escalations, cost.human_escalations),
            ("retry_count", limit.evaluator_retries, cost.retry_count),
        ]
        if arm in {
            Meas0Arm.STATE_ONLY,
            Meas0Arm.RULES_STATE,
            Meas0Arm.EVALUATION_PLANE,
        }:
            checks.extend(
                (
                    (
                        "deterministic_check_calls",
                        limit.deterministic_checks,
                        cost.deterministic_check_calls,
                    ),
                    (
                        "deterministic_wall_time_ms",
                        limit.deterministic_wall_time_ms,
                        cost.wall_time_ms,
                    ),
                )
            )
        if cost.judge_calls:
            checks.extend(
                (
                    (
                        "judge_calls",
                        limit.judge_calls_per_semantic_leaf,
                        cost.judge_calls,
                    ),
                    (
                        "input_tokens",
                        limit.judge_input_tokens * cost.judge_calls,
                        cost.input_tokens,
                    ),
                    (
                        "output_tokens",
                        limit.judge_output_tokens * cost.judge_calls,
                        cost.output_tokens,
                    ),
                    (
                        "judge_wall_time_ms",
                        limit.judge_wall_time_ms * cost.judge_calls,
                        cost.wall_time_ms,
                    ),
                )
            )
        for metric, maximum, observed in checks:
            if observed > maximum:
                return BudgetScope.ARM_CASE, metric, maximum, observed
        return None

    def _stage_violation(
        self,
    ) -> tuple[BudgetScope, str, int, int] | None:
        for metric, maximum, observed in (
            (
                "judge_calls",
                self.policy.pilot_judge_calls,
                self._stage_cost.judge_calls,
            ),
            (
                "human_escalations",
                self.policy.pilot_human_escalations,
                self._stage_cost.human_escalations,
            ),
        ):
            if observed > maximum:
                return BudgetScope.STAGE, metric, maximum, observed
        return None


__all__ = [
    "BudgetDisposition",
    "BudgetEnforcer",
    "BudgetFailureArtifact",
    "BudgetFailureCode",
    "BudgetScope",
]
