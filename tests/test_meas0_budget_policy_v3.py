from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_budget_policy_v3 import (
    BudgetPolicyV3Error,
    FrozenArmCaseBudgetLimitV3,
    FrozenMeas0BudgetPolicyV3,
    validate_frozen_meas0_budget_manifest_v3,
)
from biofield.meas0_readiness import PriceManifest, ProviderPrice
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    PhaseBudget,
    StageBudgetManifest,
)


def _price(*, direct_cap_microunits: int = 100_000_000) -> PriceManifest:
    return PriceManifest(
        manifest_id="pytest.budget-policy.price",
        version=1,
        currency="USD",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="2026-07-31T00:00:00Z",
        direct_cap_microunits=direct_cap_microunits,
        provider_prices=(
            ProviderPrice(
                provider="offline.fake",
                model_id="fake",
                input_per_million_microunits=1,
                output_per_million_microunits=1,
                metered_tool_microunits=0,
            ),
        ),
    )


def _manifest() -> StageBudgetManifest:
    phases = []
    for phase in ("jcal", "pilot", "jaudit", "confirmatory"):
        stage_cap = (
            240 if phase == "pilot" else (800 if phase == "confirmatory" else 100)
        )
        human_cap = 8 if phase == "pilot" else (22 if phase == "confirmatory" else 10)
        phases.append(
            PhaseBudget(
                phase=phase,
                max_calls=stage_cap,
                max_input_tokens=1_000_000,
                max_output_tokens=1_000_000,
                max_wall_time_ms=1_000_000,
                max_bytes_transferred=1_000_000,
                max_retries=stage_cap,
                max_monetary_microunits=100_000_000,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(
                        category=category,
                        max_calls=(
                            human_cap if category is CostCategory.HUMAN else stage_cap
                        ),
                    )
                    for category in CostCategory
                ),
            )
        )
    return StageBudgetManifest(
        manifest_id="pytest.budget-policy.stage",
        version=1,
        phase_budgets=tuple(phases),
    )


def _replace_phase(
    manifest: StageBudgetManifest,
    phase: str,
    changed: PhaseBudget,
) -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id=f"{manifest.manifest_id}.{phase}.changed",
        version=manifest.version,
        phase_budgets=tuple(
            changed if item.phase == phase else item for item in manifest.phase_budgets
        ),
    )


def test_frozen_policy_exactly_encodes_r1_r2_and_retention_rules() -> None:
    policy = FrozenMeas0BudgetPolicyV3.frozen_v1()

    assert tuple(item.task_family for item in policy.arm_case_limits) == ("r1", "r2")
    assert policy.arm_case_limits[0].task_ids == (
        "cold_chain_readiness",
        "software_release_readiness",
    )
    assert policy.arm_case_limits[1].task_ids == (
        "channel_order_ingest",
        "refund_webhook_idempotency",
    )
    assert policy.arm_case_limits[0].to_dict() == {
        "task_family": "r1",
        "task_ids": [
            "cold_chain_readiness",
            "software_release_readiness",
        ],
        "deterministic_checks": 24,
        "judge_calls_per_semantic_leaf": 2,
        "judge_input_tokens_per_call": 8_192,
        "judge_output_tokens_per_call": 1_024,
        "operational_human_escalations": 1,
        "evaluator_retries_per_measurement": 1,
        "deterministic_wall_time_ms": 60_000,
        "judge_wall_time_ms_per_call": 120_000,
    }
    assert policy.arm_case_limits[1].deterministic_checks == 32
    assert policy.arm_case_limits[1].judge_input_tokens_per_call == 16_384
    assert policy.arm_case_limits[1].deterministic_wall_time_ms == 180_000
    assert policy.failed_attempts_count_toward_budget is True
    assert policy.retries_count_toward_budget is True
    assert policy.retain_exhausted_entries is True
    assert policy.qualification_phases_excluded_from_per_arm_equality is True


def test_policy_and_validation_are_factory_only_nonclaim_objects() -> None:
    with pytest.raises(BudgetPolicyV3Error, match="frozen V1"):
        FrozenArmCaseBudgetLimitV3(
            task_family="r1",
            task_ids=("cold_chain_readiness", "software_release_readiness"),
            deterministic_checks=25,
            judge_calls_per_semantic_leaf=2,
            judge_input_tokens_per_call=8_192,
            judge_output_tokens_per_call=1_024,
            operational_human_escalations=1,
            evaluator_retries_per_measurement=1,
            deterministic_wall_time_ms=60_000,
            judge_wall_time_ms_per_call=120_000,
        )

    result = validate_frozen_meas0_budget_manifest_v3(
        phase="confirmatory",
        stage_budget_manifest=_manifest(),
        price_manifest=_price(),
    )
    assert result.claim_scope == "simulated_nonclaim"
    assert result.production_authorized is False
    assert result.cost_verified is False
    assert result.formal_eligible is False
    assert result.frozen_policy_hash == (
        FrozenMeas0BudgetPolicyV3.frozen_v1().contract_hash
    )
    with pytest.raises(BudgetPolicyV3Error, match="production authority"):
        replace(result, cost_verified=True)


@pytest.mark.parametrize(
    ("phase", "dimension", "value"),
    (
        ("pilot", "max_calls", 241),
        ("pilot", "judge_calls", 241),
        ("pilot", "human_calls", 9),
        ("confirmatory", "max_calls", 801),
        ("confirmatory", "judge_calls", 801),
        ("confirmatory", "human_calls", 23),
    ),
)
def test_stage_caps_fail_closed(
    phase: str,
    dimension: str,
    value: int,
) -> None:
    manifest = _manifest()
    selected = manifest.for_phase(phase)
    if dimension == "max_calls":
        changed = replace(selected, max_calls=value)
    else:
        category = (
            CostCategory.JUDGE if dimension == "judge_calls" else CostCategory.HUMAN
        )
        changed = replace(
            selected,
            category_call_caps=tuple(
                replace(item, max_calls=value) if item.category is category else item
                for item in selected.category_call_caps
            ),
        )

    with pytest.raises(BudgetPolicyV3Error, match="frozen.*caps"):
        validate_frozen_meas0_budget_manifest_v3(
            phase=phase,
            stage_budget_manifest=_replace_phase(manifest, phase, changed),
            price_manifest=_price(),
        )


def test_monetary_caps_bind_price_without_claiming_price_verification() -> None:
    manifest = _manifest()
    confirmatory = manifest.for_phase("confirmatory")
    over_protocol = replace(
        confirmatory,
        max_monetary_microunits=100_000_001,
    )
    with pytest.raises(BudgetPolicyV3Error, match="PriceManifest|100 USD"):
        validate_frozen_meas0_budget_manifest_v3(
            phase="confirmatory",
            stage_budget_manifest=_replace_phase(
                manifest,
                "confirmatory",
                over_protocol,
            ),
            price_manifest=_price(direct_cap_microunits=100_000_000),
        )

    with pytest.raises(BudgetPolicyV3Error, match="PriceManifest"):
        validate_frozen_meas0_budget_manifest_v3(
            phase="pilot",
            stage_budget_manifest=manifest,
            price_manifest=_price(direct_cap_microunits=99_999_999),
        )


def test_validator_rejects_unsupported_phase() -> None:
    with pytest.raises(BudgetPolicyV3Error, match="only Pilot and confirmatory"):
        validate_frozen_meas0_budget_manifest_v3(
            phase="jcal",
            stage_budget_manifest=_manifest(),
            price_manifest=_price(),
        )
