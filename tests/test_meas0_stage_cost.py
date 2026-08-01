from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_readiness import (
    FormalReadinessBundle,
    FormalReadinessInputs,
    PriceManifest,
    ProviderPrice,
    ReadinessBlockerCode,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    FORMAL_ARM_IDS,
    MonetaryCostFact,
    PhaseBudget,
    PriceManifestReceiptContract,
    PriceQuote,
    PriceQuoteReceipt,
    StageBudgetManifest,
    StageCostEntry,
    StageCostError,
    StageCostLedger,
)
from biofield.meas0_trust import SignatureEnvelope, TrustDomain


def _hash(character: str) -> str:
    return character * 64


def test_price_quote_is_typed_and_receipt_contract_cannot_be_self_asserted() -> None:
    quote = PriceQuote(
        schema_version=1,
        quote_id="candidate-quote",
        provider_id="candidate-provider",
        model_id="candidate-model",
        currency="candidate-currency",
        effective_at="2026-07-31T00:00:00Z",
        expires_at="2026-08-01T00:00:00Z",
        input_per_million_microunits=1,
        output_per_million_microunits=2,
        per_call_microunits=3,
    )
    assert quote.contract_hash == PriceQuote.from_dict(quote.to_dict()).contract_hash

    with pytest.raises(StageCostError, match="derived"):
        PriceManifestReceiptContract(
            schema_version=1,
            price_manifest_hash=_hash("a"),
            quote_receipt_hashes=(_hash("b"),),
            verification_result_hashes=(_hash("c"),),
            production_ready=True,
        )


def test_test_only_quote_rederivation_remains_production_unavailable() -> None:
    quote = PriceQuote(
        schema_version=1,
        quote_id="candidate-quote",
        provider_id="candidate-provider",
        model_id="candidate-model",
        currency="candidate-currency",
        effective_at="2026-07-31T00:00:00Z",
        expires_at="2026-08-01T00:00:00Z",
        input_per_million_microunits=1,
        output_per_million_microunits=2,
        per_call_microunits=3,
    )
    receipt = PriceQuoteReceipt(
        schema_version=1,
        quote=quote,
        envelope=SignatureEnvelope(
            schema_version=1,
            envelope_id="candidate-price-receipt",
            trust_domain=TrustDomain.TRANSPORT,
            root_id="candidate-root",
            root_manifest_hash=_hash("a"),
            key_fingerprint=_hash("b"),
            algorithm_id="candidate.test",
            role_id="candidate-price-role",
            purpose="price_quote",
            phase="jcal",
            payload_hash=quote.contract_hash,
            sequence_number=0,
            nonce="candidate-price",
            observed_signing_time="2026-07-31T00:00:00Z",
            test_only=True,
            signature_hex=_hash("c"),
        ),
    )
    manifest = PriceManifest(
        manifest_id="candidate-prices",
        version=1,
        currency="candidate-currency",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="candidate-fx-snapshot",
        direct_cap_microunits=1,
        provider_prices=(
            ProviderPrice(
                provider="candidate-provider",
                model_id="candidate-model",
                input_per_million_microunits=1,
                output_per_million_microunits=2,
                metered_tool_microunits=3,
            ),
        ),
    )

    class CandidateResult:
        contract_hash = _hash("d")

    class CandidateVerifier:
        def verify_signature_envelope(self, **_: object) -> CandidateResult:
            return CandidateResult()

    contract = PriceManifestReceiptContract.derive_from_raw_receipts(
        price_manifest=manifest,
        receipts=(receipt,),
        verifier=CandidateVerifier(),
        root_manifest=object(),
        policy=object(),
    )
    assert contract.production_ready is False
    assert contract.price_manifest_hash == manifest.contract_hash


def _budget(
    phase: str,
    *,
    max_calls: int = 10,
    counts_toward_per_arm_equality: bool | None = None,
) -> PhaseBudget:
    if counts_toward_per_arm_equality is None:
        counts_toward_per_arm_equality = phase in {"pilot", "confirmatory"}
    return PhaseBudget(
        phase=phase,
        max_calls=max_calls,
        max_input_tokens=1_000,
        max_output_tokens=1_000,
        max_wall_time_ms=10_000,
        max_bytes_transferred=100_000,
        max_retries=2,
        max_monetary_microunits=1_000_000,
        counts_toward_per_arm_equality=counts_toward_per_arm_equality,
        category_call_caps=tuple(
            CategoryCallCap(category=category, max_calls=10)
            for category in CostCategory
        ),
    )


def _budget_manifest(**overrides: PhaseBudget) -> StageBudgetManifest:
    budgets = {
        phase: _budget(phase) for phase in ("jcal", "pilot", "jaudit", "confirmatory")
    }
    budgets.update(overrides)
    return StageBudgetManifest(
        manifest_id="meas0.stage-budget.test.v1",
        version=1,
        phase_budgets=tuple(budgets.values()),
    )


def _money(amount: int, *, price_hash: str = _hash("a")) -> MonetaryCostFact:
    return MonetaryCostFact(
        price_manifest_hash=price_hash,
        derivation_basis_hash=_hash("b"),
        monetary_microunits=amount,
    )


def _entry(
    *,
    entry_id: str,
    sequence: int,
    phase: str,
    previous_entry_hash: str | None,
    category: CostCategory = CostCategory.JUDGE,
    outcome: CostOutcome = CostOutcome.SUCCEEDED,
    failure_code: str | None = None,
    calls: int = 1,
    input_tokens: int = 10,
    output_tokens: int = 5,
    wall_time_ms: int = 20,
    bytes_transferred: int = 30,
    retry_count: int = 0,
    monetary_microunits: int = 100,
    automatic_arm_execution: bool = False,
    arm_id: str | None = None,
    provider_id: str = "provider.test",
    model_id: str = "model.test",
    cost_class: str = "provider_api",
    price_hash: str = _hash("a"),
    retry_of_entry_hash: str | None = None,
    request_hash: str = _hash("c"),
) -> StageCostEntry:
    return StageCostEntry(
        entry_id=entry_id,
        sequence=sequence,
        phase=phase,
        category=category,
        outcome=outcome,
        failure_code=failure_code,
        request_hash=request_hash,
        call_hash=_hash("d"),
        raw_receipt_hash=_hash("e"),
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        wall_time_ms=wall_time_ms,
        bytes_transferred=bytes_transferred,
        retry_count=retry_count,
        monetary_microunits=monetary_microunits,
        monetary_fact=(
            _money(monetary_microunits, price_hash=price_hash)
            if monetary_microunits
            else None
        ),
        automatic_arm_execution=automatic_arm_execution,
        arm_id=arm_id,
        provider_id=provider_id,
        model_id=model_id,
        cost_class=cost_class,
        retry_of_entry_hash=retry_of_entry_hash,
        previous_entry_hash=previous_entry_hash,
    )


def _ledger(entries: tuple[StageCostEntry, ...]) -> StageCostLedger:
    return StageCostLedger(
        ledger_id="meas0.stage-cost.test.v1",
        version=1,
        price_manifest_hash=_hash("a"),
        budget_manifest=_budget_manifest(),
        entries=entries,
    )


def test_readiness_binds_stage_ledger_but_rejects_contract_only_costs() -> None:
    entry = _entry(
        entry_id="jcal-attempt-0",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    ledger = _ledger((entry,))
    bundle = FormalReadinessBundle.create(
        FormalReadinessInputs(
            stage_budget_manifest=ledger.budget_manifest,
            stage_cost_ledger=ledger,
        )
    )

    assert (
        ReadinessBlockerCode.STAGE_BUDGET_MANIFEST_MISSING not in bundle.report.blockers
    )
    assert ReadinessBlockerCode.STAGE_COST_LEDGER_MISSING not in bundle.report.blockers
    assert ReadinessBlockerCode.STAGE_COST_LEDGER_INVALID in bundle.report.blockers
    assert FormalReadinessBundle.from_dict(bundle.to_dict()) == bundle


def test_hash_chained_ledger_round_trips_and_retains_failed_call() -> None:
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    failed = _entry(
        entry_id="jcal-001",
        sequence=1,
        phase="jcal",
        previous_entry_hash=first.contract_hash,
        outcome=CostOutcome.FAILED,
        failure_code="provider_timeout",
        input_tokens=0,
        output_tokens=0,
        retry_count=1,
        retry_of_entry_hash=first.contract_hash,
        monetary_microunits=0,
    )
    ledger = _ledger((first, failed))

    restored = StageCostLedger.from_dict(ledger.to_dict())

    assert restored == ledger
    assert restored.entries[-1].outcome is CostOutcome.FAILED
    assert restored.phase_decision("jcal").retained_entry_count == 2
    assert restored.contract_hash == ledger.contract_hash


def test_append_returns_a_new_ledger_and_requires_the_exact_chain_tail() -> None:
    empty = _ledger(())
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )

    extended = empty.append(first)

    assert empty.entries == ()
    assert extended.entries == (first,)
    assert extended.contract_hash != empty.contract_hash
    with pytest.raises(StageCostError, match="chain"):
        extended.append(
            _entry(
                entry_id="jcal-001",
                sequence=1,
                phase="jcal",
                previous_entry_hash=_hash("f"),
            )
        )


def test_jcal_and_jaudit_are_independent_from_per_arm_equality() -> None:
    jcal = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    pilot = _entry(
        entry_id="pilot-000",
        sequence=1,
        phase="pilot",
        previous_entry_hash=jcal.contract_hash,
        category=CostCategory.SUBJECT,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
        monetary_microunits=200,
    )
    jaudit = _entry(
        entry_id="jaudit-000",
        sequence=2,
        phase="jaudit",
        previous_entry_hash=pilot.contract_hash,
    )
    ledger = _ledger((jcal, pilot, jaudit))

    assert ledger.all_in_totals.monetary_microunits == 400
    assert ledger.per_arm_equality_totals.monetary_microunits == 200
    assert ledger.category_totals[CostCategory.JUDGE].calls == 2
    assert ledger.category_totals[CostCategory.SUBJECT].calls == 1

    with pytest.raises(StageCostError, match="qualification phase"):
        replace(jcal, automatic_arm_execution=True)


def test_all_in_categories_cover_subject_judge_gateway_infra_and_human() -> None:
    entries: list[StageCostEntry] = []
    previous: str | None = None
    for sequence, category in enumerate(CostCategory):
        entry = _entry(
            entry_id=f"pilot-{sequence:03d}",
            sequence=sequence,
            phase="pilot",
            previous_entry_hash=previous,
            category=category,
            calls=1,
            monetary_microunits=sequence + 1,
            automatic_arm_execution=category
            in {CostCategory.SUBJECT, CostCategory.JUDGE},
            arm_id=(
                FORMAL_ARM_IDS[0]
                if category in {CostCategory.SUBJECT, CostCategory.JUDGE}
                else None
            ),
        )
        entries.append(entry)
        previous = entry.contract_hash

    ledger = _ledger(tuple(entries))

    assert set(ledger.category_totals) == set(CostCategory)
    assert ledger.all_in_totals.monetary_microunits == 15
    assert ledger.per_arm_equality_totals.monetary_microunits == 3


def test_budget_crossing_retains_trigger_and_stops_phase() -> None:
    budget = _budget_manifest(jcal=_budget("jcal", max_calls=1))
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    trigger = _entry(
        entry_id="jcal-001",
        sequence=1,
        phase="jcal",
        previous_entry_hash=first.contract_hash,
    )
    ledger = StageCostLedger(
        ledger_id="meas0.stage-cost.test.v1",
        version=1,
        price_manifest_hash=_hash("a"),
        budget_manifest=budget,
        entries=(first, trigger),
    )

    decision = ledger.phase_decision("jcal")
    assert decision.stopped is True
    assert decision.trigger_entry_hash == trigger.contract_hash
    assert decision.exceeded_dimensions == ("calls",)
    assert decision.retained_entry_count == 2

    after_stop = _entry(
        entry_id="jcal-002",
        sequence=2,
        phase="jcal",
        previous_entry_hash=trigger.contract_hash,
        request_hash=_hash("f"),
    )
    with pytest.raises(StageCostError, match="after phase budget stop"):
        replace(ledger, entries=(first, trigger, after_stop))


def test_post_call_crossing_retains_remaining_attempts_from_same_request() -> None:
    budget = _budget_manifest(jcal=_budget("jcal", max_calls=1))
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    trigger = _entry(
        entry_id="jcal-001",
        sequence=1,
        phase="jcal",
        previous_entry_hash=first.contract_hash,
    )
    same_completed_request = _entry(
        entry_id="jcal-002",
        sequence=2,
        phase="jcal",
        previous_entry_hash=trigger.contract_hash,
    )

    ledger = StageCostLedger(
        ledger_id="meas0.stage-cost.test.v1",
        version=1,
        price_manifest_hash=_hash("a"),
        budget_manifest=budget,
        entries=(first, trigger, same_completed_request),
    )

    assert ledger.phase_decision("jcal").trigger_entry_hash == trigger.contract_hash
    assert ledger.phase_decision("jcal").retained_entry_count == 3

    disguised_retry = _entry(
        entry_id="jcal-003",
        sequence=3,
        phase="jcal",
        previous_entry_hash=same_completed_request.contract_hash,
        retry_count=1,
        retry_of_entry_hash=trigger.contract_hash,
    )
    with pytest.raises(StageCostError, match="after phase budget stop"):
        replace(
            ledger,
            entries=(*ledger.entries, disguised_retry),
        )

    changed_backend = replace(
        same_completed_request,
        provider_id="different-provider",
    )
    changed_backend = replace(
        changed_backend,
        previous_entry_hash=trigger.contract_hash,
    )
    with pytest.raises(StageCostError, match="after phase budget stop"):
        StageCostLedger(
            ledger_id=ledger.ledger_id,
            version=ledger.version,
            price_manifest_hash=ledger.price_manifest_hash,
            budget_manifest=ledger.budget_manifest,
            entries=(first, trigger, changed_backend),
        )


def test_missing_or_invalid_phase_budget_fails_closed() -> None:
    with pytest.raises(StageCostError, match="exactly one budget"):
        StageBudgetManifest(
            manifest_id="missing-jaudit",
            version=1,
            phase_budgets=(
                _budget("jcal"),
                _budget("pilot"),
                _budget("confirmatory"),
            ),
        )

    with pytest.raises(StageCostError, match="qualification phase"):
        _budget(
            "jcal",
            counts_toward_per_arm_equality=True,
        )


def test_price_ancestry_is_required_and_must_match_ledger() -> None:
    with pytest.raises(StageCostError, match="monetary fact"):
        replace(
            _entry(
                entry_id="jcal-000",
                sequence=0,
                phase="jcal",
                previous_entry_hash=None,
            ),
            monetary_fact=None,
        )

    wrong_price = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
        price_hash=_hash("f"),
    )
    with pytest.raises(StageCostError, match="PriceManifest ancestry"):
        _ledger((wrong_price,))


def test_tamper_duplicate_order_and_chain_break_fail_closed() -> None:
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    second = _entry(
        entry_id="pilot-000",
        sequence=1,
        phase="pilot",
        previous_entry_hash=first.contract_hash,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
    )
    ledger = _ledger((first, second))

    tampered = ledger.to_dict()
    tampered["entries"][0]["input_tokens"] = 999
    with pytest.raises(StageCostError, match="hash"):
        StageCostLedger.from_dict(tampered)

    with pytest.raises(StageCostError, match="duplicate"):
        replace(ledger, entries=(first, replace(second, entry_id=first.entry_id)))
    with pytest.raises(StageCostError, match="sequence"):
        replace(ledger, entries=(first, replace(second, sequence=2)))
    with pytest.raises(StageCostError, match="chain"):
        replace(
            ledger, entries=(first, replace(second, previous_entry_hash=_hash("f")))
        )
    pilot_first = replace(first, phase="pilot")
    jcal_second = replace(
        second,
        phase="jcal",
        automatic_arm_execution=False,
        arm_id=None,
        previous_entry_hash=pilot_first.contract_hash,
    )
    with pytest.raises(StageCostError, match="phase order"):
        replace(ledger, entries=(pilot_first, jcal_second))


def test_failure_shape_and_zero_cost_price_fact_are_canonical() -> None:
    success = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    with pytest.raises(StageCostError, match="failure_code"):
        replace(success, failure_code="not-a-success")
    with pytest.raises(StageCostError, match="failure_code"):
        replace(success, outcome=CostOutcome.FAILED)
    with pytest.raises(StageCostError, match="zero monetary"):
        replace(success, monetary_fact=_money(0))


def test_automatic_entries_require_a_frozen_arm_and_nonautomatic_entries_do_not() -> (
    None
):
    base = _entry(
        entry_id="pilot-000",
        sequence=0,
        phase="pilot",
        previous_entry_hash=None,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
    )

    assert base.arm_id == FORMAL_ARM_IDS[0]
    with pytest.raises(StageCostError, match="frozen arm"):
        replace(base, arm_id="not-an-arm")
    with pytest.raises(StageCostError, match="arm_id"):
        replace(base, arm_id=None)
    with pytest.raises(StageCostError, match="non-automatic"):
        replace(base, automatic_arm_execution=False)
    with pytest.raises(StageCostError, match="automatic arm"):
        replace(base, phase="jcal")


def test_each_entry_is_one_attempt_and_retry_is_a_separate_bound_entry() -> None:
    first = _entry(
        entry_id="pilot-000",
        sequence=0,
        phase="pilot",
        previous_entry_hash=None,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
    )
    retry = _entry(
        entry_id="pilot-001",
        sequence=1,
        phase="pilot",
        previous_entry_hash=first.contract_hash,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
        retry_count=1,
        retry_of_entry_hash=first.contract_hash,
    )

    ledger = _ledger((first, retry))
    assert ledger.all_in_totals.calls == 2
    assert ledger.all_in_totals.retry_count == 1
    with pytest.raises(StageCostError, match="exactly one attempt"):
        replace(first, calls=2)
    with pytest.raises(StageCostError, match="retry"):
        replace(first, retry_count=1)
    with pytest.raises(StageCostError, match="retry ancestry"):
        replace(
            ledger,
            entries=(
                first,
                replace(retry, retry_of_entry_hash=_hash("f")),
            ),
        )


def test_entry_requires_provider_model_and_cost_class_identity() -> None:
    entry = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )

    with pytest.raises(StageCostError, match="provider_id"):
        replace(entry, provider_id="")
    with pytest.raises(StageCostError, match="model_id"):
        replace(entry, model_id="")
    with pytest.raises(StageCostError, match="cost_class"):
        replace(entry, cost_class="")


def test_category_specific_phase_cap_retains_trigger_and_stops() -> None:
    caps = tuple(
        CategoryCallCap(
            category=category,
            max_calls=1 if category is CostCategory.JUDGE else 10,
        )
        for category in CostCategory
    )
    budget = _budget_manifest(
        jcal=replace(_budget("jcal"), max_calls=10, category_call_caps=caps)
    )
    first = _entry(
        entry_id="jcal-000",
        sequence=0,
        phase="jcal",
        previous_entry_hash=None,
    )
    trigger = _entry(
        entry_id="jcal-001",
        sequence=1,
        phase="jcal",
        previous_entry_hash=first.contract_hash,
    )
    ledger = StageCostLedger(
        ledger_id="meas0.stage-cost.test.v1",
        version=1,
        price_manifest_hash=_hash("a"),
        budget_manifest=budget,
        entries=(first, trigger),
    )

    decision = ledger.phase_decision("jcal")
    assert decision.stopped is True
    assert decision.exceeded_dimensions == ("category_calls:judge",)
    with pytest.raises(StageCostError, match="exactly one cap"):
        replace(
            budget.for_phase("jcal"),
            category_call_caps=caps[:-1],
        )


def test_phase_arm_category_totals_are_derived_and_production_ready_is_false() -> None:
    subject = _entry(
        entry_id="pilot-000",
        sequence=0,
        phase="pilot",
        previous_entry_hash=None,
        category=CostCategory.SUBJECT,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[0],
        monetary_microunits=200,
    )
    judge = _entry(
        entry_id="pilot-001",
        sequence=1,
        phase="pilot",
        previous_entry_hash=subject.contract_hash,
        category=CostCategory.JUDGE,
        automatic_arm_execution=True,
        arm_id=FORMAL_ARM_IDS[1],
        monetary_microunits=300,
    )
    ledger = _ledger((subject, judge))

    totals = ledger.phase_arm_category_totals
    assert totals["pilot"][FORMAL_ARM_IDS[0]]["subject"].monetary_microunits == 200
    assert totals["pilot"][FORMAL_ARM_IDS[1]]["judge"].monetary_microunits == 300
    assert ledger.production_ready is False
    assert ledger.to_dict()["production_ready"] is False

    forged = ledger.to_dict()
    forged["production_ready"] = True
    with pytest.raises(StageCostError, match="production_ready"):
        StageCostLedger.from_dict(forged)
