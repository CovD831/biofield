from __future__ import annotations

import json
from dataclasses import replace
from itertools import permutations

import pytest

from biofield.atomic_commitment import (
    AtomicCommitmentBatch,
    _batch_hash,
    _canonical_hash,
    materialize_atomic_commitments,
    replay_atomic_commitments,
)
from biofield.contracts import ResourceAmount, ResourceEvent, ResourceOperation
from biofield.multi_admission import resolve_multi_admission
from test_multi_admission import _candidate, _policy, _single_policy


def _inputs(candidates=None, **overrides):
    values = {
        "candidates": tuple(
            candidates
            or (
                _candidate("bid-b", "agent-b", tokens=40),
                _candidate("bid-a", "agent-a", tokens=40),
            )
        ),
        "run_budget": (ResourceAmount("tokens", 100),),
        "reserved_resources": (),
        "existing_requirement_loads": (),
        "ready_requirement_ids": ("sources",),
        "current_concurrency": 0,
        "admission_policy": _single_policy(),
        "policy": _policy(),
        "at": "2026-07-30T09:00:30+08:00",
        "run_finalized": False,
        "prior_resource_events": (),
        "prior_public_events": (),
    }
    values.update(overrides)
    resolver_keys = {
        "candidates",
        "run_budget",
        "reserved_resources",
        "existing_requirement_loads",
        "ready_requirement_ids",
        "current_concurrency",
        "admission_policy",
        "policy",
        "at",
        "run_finalized",
    }
    selection = resolve_multi_admission(
        **{key: value for key, value in values.items() if key in resolver_keys}
    )
    return {"selection": selection, **values}


def _resign(batch: AtomicCommitmentBatch, **overrides) -> str:
    values = {
        "candidates": batch.candidates,
        "run_budget": batch.run_budget,
        "reserved_resources": batch.reserved_resources,
        "existing_requirement_loads": batch.existing_requirement_loads,
        "ready_requirement_ids": batch.ready_requirement_ids,
        "current_concurrency": batch.current_concurrency,
        "admission_policy": batch.admission_policy,
        "multi_admission_policy": batch.multi_admission_policy,
        "at": batch.at,
        "run_finalized": batch.run_finalized,
        "prior_resource_events": batch.prior_resource_events,
        "prior_public_events": batch.prior_public_events,
        "selection": batch.selection,
        "entries": batch.entries,
        "appended_resource_events": batch.appended_resource_events,
        "appended_public_events": batch.appended_public_events,
        "pre_ledger_totals": batch.pre_ledger_totals,
        "ledger_totals": batch.ledger_totals,
        "prior_resource_event_ids": batch.prior_resource_event_ids,
        "prior_public_event_ids": batch.prior_public_event_ids,
        "public_revision_start": batch.public_revision_start,
        "public_parent_id": batch.public_parent_id,
    }
    values.update(overrides)
    return _batch_hash(**values)


def test_two_admitted_bids_materialize_all_at_once_in_stable_order() -> None:
    batch = materialize_atomic_commitments(**_inputs())

    assert tuple(entry.bid_id for entry in batch.entries) == ("bid-a", "bid-b")
    assert all(entry.decision.commitment is not None for entry in batch.entries)
    assert all(entry.lifecycle.revision == 0 for entry in batch.entries)
    assert tuple(event.event_type for event in batch.appended_public_events) == (
        "multi_admission_selected",
        "resource_grant",
        "commitment_materialized",
        "resource_grant",
        "commitment_materialized",
    )
    assert len(batch.appended_resource_events) == 2
    assert batch.ledger_totals["tokens"]["shared_pool"] == "20"
    assert batch.production_authorized is False
    assert batch.scientific_claim is False
    assert (
        batch.claim_scope == "deterministic_offline_atomic_proposal_construction_only"
    )


def test_candidate_permutations_have_identical_serialization_and_hash() -> None:
    candidates = (
        _candidate("bid-b", "agent-b", tokens=40),
        _candidate("bid-a", "agent-a", tokens=40),
    )
    batches = [
        materialize_atomic_commitments(**_inputs(order))
        for order in permutations(candidates)
    ]

    assert batches[0] == batches[1]
    assert batches[0].to_json() == batches[1].to_json()
    assert batches[0].batch_sha256 == batches[1].batch_sha256


def test_forged_selection_or_partial_admission_cannot_materialize() -> None:
    inputs = _inputs()
    forged = replace(inputs["selection"], input_sha256="0" * 64)
    with pytest.raises(ValueError, match="selection"):
        materialize_atomic_commitments(**{**inputs, "selection": forged})

    one_fits = _inputs(
        (
            _candidate("bid-a", "agent-a", tokens=60),
            _candidate("bid-b", "agent-b", tokens=50),
        )
    )
    assert one_fits["selection"].admitted_bid_ids == ("bid-a",)
    with pytest.raises(ValueError, match="at least two"):
        materialize_atomic_commitments(**one_fits)


def test_duplicate_dependency_resource_and_finalized_fail_without_partial_state() -> (
    None
):
    prior_resource_events: tuple[ResourceEvent, ...] = ()
    cases = (
        lambda: _inputs(
            (
                _candidate("bid-a", "agent-a"),
                _candidate("bid-a", "agent-b"),
            )
        ),
        lambda: _inputs(
            (
                _candidate("bid-a", "agent-a", requirement_id="answer"),
                _candidate("bid-b", "agent-b"),
            )
        ),
        lambda: _inputs(run_budget=(ResourceAmount("tokens", 70),)),
        lambda: _inputs(run_finalized=True),
    )

    for make_inputs in cases:
        with pytest.raises(ValueError):
            materialize_atomic_commitments(**make_inputs())
        assert prior_resource_events == ()


def test_prior_ledger_conflicts_and_reserved_mismatch_fail_closed() -> None:
    prior = ResourceEvent(
        event_id="prior-grant",
        operation=ResourceOperation.GRANT,
        resource_type="tokens",
        amount=10,
        source_account="SharedPool",
        target_account="AgentEscrow[prior]",
        idempotency_key="prior-grant",
    )
    conflicting = replace(prior, amount=11)

    with pytest.raises(ValueError):
        materialize_atomic_commitments(
            **_inputs(
                prior_resource_events=(prior, conflicting),
                reserved_resources=(ResourceAmount("tokens", 10),),
            )
        )
    with pytest.raises(ValueError, match="reserved_resources"):
        materialize_atomic_commitments(**_inputs(prior_resource_events=(prior,)))


def test_prior_resource_and_public_event_ids_share_one_global_namespace() -> None:
    seed_batch = materialize_atomic_commitments(**_inputs())
    prior_resource = ResourceEvent(
        event_id="globally-duplicated-id",
        operation=ResourceOperation.GRANT,
        resource_type="tokens",
        amount=10,
        source_account="SharedPool",
        target_account="AgentEscrow[prior]",
        idempotency_key="prior-global-id",
    )
    prior_public = replace(
        seed_batch.appended_public_events[0],
        event_id=prior_resource.event_id,
        public_state_revision=0,
        causal_parent_ids=(),
    )

    with pytest.raises(ValueError, match="globally unique"):
        materialize_atomic_commitments(
            **_inputs(
                prior_resource_events=(prior_resource,),
                prior_public_events=(prior_public,),
                reserved_resources=(ResourceAmount("tokens", 10),),
            )
        )


def test_reserved_comparison_is_exact_beyond_float_integer_precision() -> None:
    exact = 2**53
    prior = ResourceEvent(
        event_id="prior-large-grant",
        operation=ResourceOperation.GRANT,
        resource_type="tokens",
        amount=exact,
        source_account="SharedPool",
        target_account="AgentEscrow[prior]",
        idempotency_key="prior-large-grant",
    )

    with pytest.raises(ValueError, match="reserved_resources"):
        materialize_atomic_commitments(
            **_inputs(
                run_budget=(ResourceAmount("tokens", exact + 100),),
                prior_resource_events=(prior,),
                reserved_resources=(ResourceAmount("tokens", exact + 1),),
            )
        )


def test_injected_exception_after_preflight_exposes_no_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import biofield.atomic_commitment as module

    inputs = _inputs()
    prior_resources = inputs["prior_resource_events"]
    prior_public = inputs["prior_public_events"]

    def explode() -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(module, "_after_preflight_hook", explode)
    with pytest.raises(RuntimeError, match="injected"):
        materialize_atomic_commitments(**inputs)
    assert inputs["prior_resource_events"] is prior_resources
    assert inputs["prior_public_events"] is prior_public


def test_replay_and_strict_typed_restore_rederive_exact_batch() -> None:
    inputs = _inputs()
    batch = materialize_atomic_commitments(**inputs)

    assert replay_atomic_commitments(batch=batch, **inputs) == batch
    restored = AtomicCommitmentBatch.restore_from_typed_sources(
        json.loads(batch.to_json()),
        **inputs,
    )
    assert restored == batch

    tampered = json.loads(batch.to_json())
    tampered["appended_public_events"][1]["event_type"] = "other"
    with pytest.raises(ValueError, match="strict"):
        AtomicCommitmentBatch.restore_from_typed_sources(tampered, **inputs)

    reordered = json.loads(batch.to_json())
    reordered["entries"].reverse()
    with pytest.raises(ValueError, match="strict"):
        AtomicCommitmentBatch.restore_from_typed_sources(reordered, **inputs)

    boolean_alias = json.loads(batch.to_json())
    boolean_alias["schema_version"] = True
    with pytest.raises(ValueError, match="strict"):
        AtomicCommitmentBatch.restore_from_typed_sources(boolean_alias, **inputs)


def test_replace_grant_and_self_reported_totals_cannot_resign_batch() -> None:
    batch = materialize_atomic_commitments(**_inputs())
    first = batch.entries[0]
    forged_grant = replace(first.resource_grants[0], amount=41)

    with pytest.raises(ValueError):
        replace(first, resource_grants=(forged_grant,))

    forged_totals = {
        resource_type: dict(totals)
        for resource_type, totals in batch.ledger_totals.items()
    }
    forged_totals["tokens"]["shared_pool"] = "19"
    forged_totals["tokens"]["escrow"] = "81"
    resigned = _resign(batch, ledger_totals=forged_totals)
    with pytest.raises(ValueError):
        replace(
            batch,
            ledger_totals=forged_totals,
            batch_sha256=resigned,
        )


def test_bare_batch_cannot_self_sign_forged_pre_and_post_totals() -> None:
    batch = materialize_atomic_commitments(**_inputs())
    forged_pre = {
        "tokens": {
            "expected": "999",
            "shared_pool": "999",
            "escrow": "0",
            "reserved": "0",
            "spent": "0",
        }
    }
    forged_post = {
        "tokens": {
            "expected": "999",
            "shared_pool": "919",
            "escrow": "80",
            "reserved": "0",
            "spent": "0",
        }
    }
    resigned = _resign(
        batch,
        pre_ledger_totals=forged_pre,
        ledger_totals=forged_post,
    )

    with pytest.raises(ValueError):
        replace(
            batch,
            pre_ledger_totals=forged_pre,
            ledger_totals=forged_post,
            batch_sha256=resigned,
        )


def test_bare_batch_cannot_self_sign_ghost_prior_ids() -> None:
    batch = materialize_atomic_commitments(**_inputs())
    ghost_ids = ("ghost-prior-resource-event",)
    resigned = _resign(batch, prior_resource_event_ids=ghost_ids)

    with pytest.raises(ValueError):
        replace(
            batch,
            prior_resource_event_ids=ghost_ids,
            batch_sha256=resigned,
        )


@pytest.mark.parametrize(
    "mutation",
    ("revision", "parent", "payload", "event_id", "duplicate_global_id"),
)
def test_public_event_stream_is_exact_and_cannot_be_rehashed(
    mutation: str,
) -> None:
    batch = materialize_atomic_commitments(**_inputs())
    events = list(batch.appended_public_events)
    target = events[1]
    changes = {}
    if mutation == "revision":
        changes["public_state_revision"] = target.public_state_revision + 1
    elif mutation == "parent":
        changes["causal_parent_ids"] = ()
    elif mutation == "payload":
        payload = dict(target.payload)
        payload["amount"] = 41
        changes["payload"] = payload
        changes["payload_sha256"] = _canonical_hash(payload)
    elif mutation == "event_id":
        changes["event_id"] = "forged-public-id"
    else:
        changes["event_id"] = batch.appended_resource_events[0].event_id
    events[1] = replace(target, **changes)
    resigned = _resign(batch, appended_public_events=tuple(events))

    with pytest.raises(ValueError):
        replace(
            batch,
            appended_public_events=tuple(events),
            batch_sha256=resigned,
        )


def test_multi_resource_ids_are_distinct_and_global_event_ids_are_unique() -> None:
    def with_calls(candidate):
        resources = (
            ResourceAmount("tokens", 20),
            ResourceAmount("calls", 1),
        )
        return replace(
            candidate,
            bid=replace(
                candidate.bid,
                requested_budget_vector=resources,
                estimated_cost_vector=resources,
            ),
            intent=replace(
                candidate.intent,
                requested_resource_bounds=resources,
            ),
            observation=replace(
                candidate.observation,
                resource_terms=(
                    ResourceAmount("tokens", 200),
                    ResourceAmount("calls", 10),
                ),
            ),
        )

    candidate_a = with_calls(_candidate("bid-a", "agent-a", tokens=20))
    candidate_b = with_calls(_candidate("bid-b", "agent-b", tokens=20))
    batch = materialize_atomic_commitments(
        **_inputs(
            (candidate_a, candidate_b),
            run_budget=(
                ResourceAmount("tokens", 100),
                ResourceAmount("calls", 10),
            ),
        )
    )
    all_ids = tuple(
        event.event_id
        for event in (
            *batch.appended_resource_events,
            *batch.appended_public_events,
        )
    )
    assert len(all_ids) == len(set(all_ids))


def test_existing_single_commitment_resolver_remains_available() -> None:
    from biofield.admission import resolve_admission

    assert callable(resolve_admission)
