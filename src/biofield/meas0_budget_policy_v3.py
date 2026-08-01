"""Frozen MEAS0 V3 budget-policy validation for offline plan construction.

This module validates that a caller-supplied ``StageBudgetManifest`` is no
more permissive than the unchanged V1 stage maxima and binds the unchanged
R1/R2 per-arm-case limits.  It does not verify prices, usage, FX, provider
metering, wall time, tokens, human payments, or any incurred cost.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .meas0_readiness import PriceManifest
from .meas0_stage_cost import CostCategory, StageBudgetManifest


class BudgetPolicyV3Error(ValueError):
    """The supplied budget surface exceeds or diverges from frozen V1 rules."""


_POLICY_TOKEN = object()
_VALIDATION_TOKEN = object()
_PHASE_MAXIMA = {
    "pilot": {
        "judge_calls": 240,
        "human_escalations": 8,
        "direct_monetary_microunits": None,
    },
    "confirmatory": {
        "judge_calls": 800,
        "human_escalations": 22,
        "direct_monetary_microunits": 100_000_000,
    },
}
_TASK_LIMITS = (
    (
        "r1",
        ("cold_chain_readiness", "software_release_readiness"),
        24,
        2,
        8_192,
        1_024,
        1,
        1,
        60_000,
        120_000,
    ),
    (
        "r2",
        ("channel_order_ingest", "refund_webhook_idempotency"),
        32,
        2,
        16_384,
        1_024,
        1,
        1,
        180_000,
        120_000,
    ),
)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _validation_body(
    *,
    phase: str,
    stage_budget_manifest_hash: str,
    price_manifest_hash: str,
    frozen_policy_hash: str,
) -> dict[str, object]:
    return {
        "schema": "meas0.offline-budget-validation.v3",
        "version": 1,
        "phase": phase,
        "stage_budget_manifest_hash": stage_budget_manifest_hash,
        "price_manifest_hash": price_manifest_hash,
        "frozen_policy_hash": frozen_policy_hash,
        "claim_scope": "simulated_nonclaim",
        "production_authorized": False,
        "cost_verified": False,
        "formal_eligible": False,
    }


@dataclass(frozen=True)
class FrozenArmCaseBudgetLimitV3:
    """One frozen R1/R2 limit shared by Pilot and confirmatory task variants."""

    task_family: str
    task_ids: tuple[str, str]
    deterministic_checks: int
    judge_calls_per_semantic_leaf: int
    judge_input_tokens_per_call: int
    judge_output_tokens_per_call: int
    operational_human_escalations: int
    evaluator_retries_per_measurement: int
    deterministic_wall_time_ms: int
    judge_wall_time_ms_per_call: int
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        expected = next(
            (item for item in _TASK_LIMITS if item[0] == self.task_family),
            None,
        )
        observed = (
            self.task_family,
            self.task_ids,
            self.deterministic_checks,
            self.judge_calls_per_semantic_leaf,
            self.judge_input_tokens_per_call,
            self.judge_output_tokens_per_call,
            self.operational_human_escalations,
            self.evaluator_retries_per_measurement,
            self.deterministic_wall_time_ms,
            self.judge_wall_time_ms_per_call,
        )
        if self._factory_token is not _POLICY_TOKEN or observed != expected:
            raise BudgetPolicyV3Error(
                "per-arm-case budget differs from the frozen V1 R1/R2 policy"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "task_family": self.task_family,
            "task_ids": list(self.task_ids),
            "deterministic_checks": self.deterministic_checks,
            "judge_calls_per_semantic_leaf": self.judge_calls_per_semantic_leaf,
            "judge_input_tokens_per_call": self.judge_input_tokens_per_call,
            "judge_output_tokens_per_call": self.judge_output_tokens_per_call,
            "operational_human_escalations": self.operational_human_escalations,
            "evaluator_retries_per_measurement": (
                self.evaluator_retries_per_measurement
            ),
            "deterministic_wall_time_ms": self.deterministic_wall_time_ms,
            "judge_wall_time_ms_per_call": self.judge_wall_time_ms_per_call,
        }


@dataclass(frozen=True)
class FrozenMeas0BudgetPolicyV3:
    """Factory-only encoding of the unchanged V1 budget semantics."""

    schema: str
    version: int
    arm_case_limits: tuple[FrozenArmCaseBudgetLimitV3, ...]
    failed_attempts_count_toward_budget: bool
    retries_count_toward_budget: bool
    retain_exhausted_entries: bool
    qualification_phases_excluded_from_per_arm_equality: bool
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _POLICY_TOKEN
            or self.schema != "meas0.frozen-budget-policy.v3"
            or self.version != 1
            or tuple(item.task_family for item in self.arm_case_limits) != ("r1", "r2")
            or not all(
                isinstance(item, FrozenArmCaseBudgetLimitV3)
                for item in self.arm_case_limits
            )
            or self.failed_attempts_count_toward_budget is not True
            or self.retries_count_toward_budget is not True
            or self.retain_exhausted_entries is not True
            or self.qualification_phases_excluded_from_per_arm_equality is not True
        ):
            raise BudgetPolicyV3Error(
                "frozen MEAS0 budget policy is not factory-derived"
            )

    @classmethod
    def frozen_v1(cls) -> FrozenMeas0BudgetPolicyV3:
        limits = tuple(
            FrozenArmCaseBudgetLimitV3(
                task_family=item[0],
                task_ids=item[1],
                deterministic_checks=item[2],
                judge_calls_per_semantic_leaf=item[3],
                judge_input_tokens_per_call=item[4],
                judge_output_tokens_per_call=item[5],
                operational_human_escalations=item[6],
                evaluator_retries_per_measurement=item[7],
                deterministic_wall_time_ms=item[8],
                judge_wall_time_ms_per_call=item[9],
                _factory_token=_POLICY_TOKEN,
            )
            for item in _TASK_LIMITS
        )
        return cls(
            schema="meas0.frozen-budget-policy.v3",
            version=1,
            arm_case_limits=limits,
            failed_attempts_count_toward_budget=True,
            retries_count_toward_budget=True,
            retain_exhausted_entries=True,
            qualification_phases_excluded_from_per_arm_equality=True,
            _factory_token=_POLICY_TOKEN,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "arm_case_limits": [item.to_dict() for item in self.arm_case_limits],
            "failed_attempts_count_toward_budget": (
                self.failed_attempts_count_toward_budget
            ),
            "retries_count_toward_budget": self.retries_count_toward_budget,
            "retain_exhausted_entries": self.retain_exhausted_entries,
            "qualification_phases_excluded_from_per_arm_equality": (
                self.qualification_phases_excluded_from_per_arm_equality
            ),
        }

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class OfflineBudgetValidationV3:
    """Non-authoritative proof that one manifest stays within frozen maxima."""

    phase: str
    stage_budget_manifest_hash: str
    price_manifest_hash: str
    frozen_policy_hash: str
    claim_scope: str
    production_authorized: bool
    cost_verified: bool
    formal_eligible: bool
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _VALIDATION_TOKEN
            or self.phase not in _PHASE_MAXIMA
            or self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.cost_verified is not False
            or self.formal_eligible is not False
        ):
            raise BudgetPolicyV3Error(
                "offline budget validation cannot carry production authority"
            )
        for value in (
            self.stage_budget_manifest_hash,
            self.price_manifest_hash,
            self.frozen_policy_hash,
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise BudgetPolicyV3Error(
                    "offline budget validation ancestry hash is invalid"
                )

    def to_dict(self) -> dict[str, object]:
        return _validation_body(
            phase=self.phase,
            stage_budget_manifest_hash=self.stage_budget_manifest_hash,
            price_manifest_hash=self.price_manifest_hash,
            frozen_policy_hash=self.frozen_policy_hash,
        )

    @property
    def validation_hash(self) -> str:
        return _canonical_hash(self.to_dict())


def validate_frozen_meas0_budget_manifest_v3(
    *,
    phase: str,
    stage_budget_manifest: StageBudgetManifest,
    price_manifest: PriceManifest,
) -> OfflineBudgetValidationV3:
    """Reject a Pilot/confirmatory budget that exceeds frozen V1 maxima."""

    if phase not in _PHASE_MAXIMA:
        raise BudgetPolicyV3Error(
            "frozen budget validation supports only Pilot and confirmatory"
        )
    if not isinstance(stage_budget_manifest, StageBudgetManifest):
        raise BudgetPolicyV3Error(
            "frozen budget validation requires typed StageBudgetManifest"
        )
    if not isinstance(price_manifest, PriceManifest):
        raise BudgetPolicyV3Error(
            "frozen budget validation requires typed PriceManifest"
        )

    selected = stage_budget_manifest.for_phase(phase)
    maxima = _PHASE_MAXIMA[phase]
    judge_cap = maxima["judge_calls"]
    human_cap = maxima["human_escalations"]
    if (
        selected.max_calls > judge_cap
        or selected.category_call_cap(CostCategory.JUDGE) > judge_cap
        or selected.category_call_cap(CostCategory.HUMAN) > human_cap
    ):
        raise BudgetPolicyV3Error(
            f"{phase} budget exceeds the frozen Judge/human stage caps"
        )
    if selected.max_monetary_microunits > price_manifest.direct_cap_microunits:
        raise BudgetPolicyV3Error(
            f"{phase} budget exceeds its bound PriceManifest direct cap"
        )
    direct_cap = maxima["direct_monetary_microunits"]
    if phase == "confirmatory" and (
        price_manifest.currency != "USD"
        or price_manifest.direct_cap_microunits > direct_cap
        or selected.max_monetary_microunits > direct_cap
    ):
        raise BudgetPolicyV3Error(
            "confirmatory budget exceeds the frozen 100 USD direct cap"
        )

    for qualification_phase in ("jcal", "jaudit"):
        if stage_budget_manifest.for_phase(
            qualification_phase
        ).counts_toward_per_arm_equality:
            raise BudgetPolicyV3Error(
                "J-CAL/J-AUDIT budgets cannot enter per-arm equality"
            )

    frozen_policy = FrozenMeas0BudgetPolicyV3.frozen_v1()
    return OfflineBudgetValidationV3(
        phase=phase,
        stage_budget_manifest_hash=stage_budget_manifest.contract_hash,
        price_manifest_hash=price_manifest.contract_hash,
        frozen_policy_hash=frozen_policy.contract_hash,
        claim_scope="simulated_nonclaim",
        production_authorized=False,
        cost_verified=False,
        formal_eligible=False,
        _factory_token=_VALIDATION_TOKEN,
    )


def expected_offline_budget_validation_hash_v3(
    *,
    phase: str,
    stage_budget_manifest_hash: str,
    price_manifest_hash: str,
) -> str:
    """Rebuild the nonclaim validation binding from already-validated hashes."""

    if phase not in _PHASE_MAXIMA:
        raise BudgetPolicyV3Error("offline budget validation phase is invalid")
    for value in (stage_budget_manifest_hash, price_manifest_hash):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise BudgetPolicyV3Error(
                "offline budget validation ancestry hash is invalid"
            )
    return _canonical_hash(
        _validation_body(
            phase=phase,
            stage_budget_manifest_hash=stage_budget_manifest_hash,
            price_manifest_hash=price_manifest_hash,
            frozen_policy_hash=FrozenMeas0BudgetPolicyV3.frozen_v1().contract_hash,
        )
    )


__all__ = [
    "BudgetPolicyV3Error",
    "expected_offline_budget_validation_hash_v3",
    "FrozenArmCaseBudgetLimitV3",
    "FrozenMeas0BudgetPolicyV3",
    "OfflineBudgetValidationV3",
    "validate_frozen_meas0_budget_manifest_v3",
]
