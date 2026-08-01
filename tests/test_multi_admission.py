from __future__ import annotations

import json
from itertools import permutations

from biofield.admission import ActionToolPolicy, AdmissionPolicy
from biofield.contracts import (
    AgentBid,
    AgentIntent,
    LocalFieldObservation,
    ResourceAmount,
)
from biofield.multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionReason,
    MultiAdmissionResult,
    MultiAdmissionStatus,
    RequirementLoad,
    resolve_multi_admission,
)


def _candidate(
    bid_id: str,
    agent_id: str,
    *,
    tokens: int = 40,
    requirement_id: str = "sources",
    exploration: bool = False,
    risk_flags: tuple[str, ...] = (),
    intent_id: str | None = None,
) -> BidCandidate:
    observation_id = f"observation-{agent_id}"
    actual_intent_id = intent_id or f"intent-{agent_id}"
    observation = LocalFieldObservation(
        schema_version=1,
        observation_id=observation_id,
        agent_id=agent_id,
        task_id="task-1",
        requirement_schema_version=1,
        public_state_revision=1,
        visible_requirement_signals=(requirement_id,),
        congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 200),),
        risk_flags=risk_flags,
        source_event_ids=(f"event-{agent_id}",),
        field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:05:00+08:00",
    )
    intent = AgentIntent(
        schema_version=1,
        intent_id=actual_intent_id,
        agent_id=agent_id,
        observation_id=observation_id,
        local_state_version=0,
        target_requirement_id=requirement_id,
        proposed_action_family="fixture_lookup",
        expected_evidence_type="source-record",
        expected_marginal_progress=0.5,
        confidence=0.5,
        uncertainty=0.5,
        requested_resource_bounds=(ResourceAmount("tokens", tokens),),
        dependency_refs=(),
        expires_at="2026-07-30T09:04:00+08:00",
    )
    bid = AgentBid(
        schema_version=1,
        bid_id=bid_id,
        agent_id=agent_id,
        intent_id=actual_intent_id,
        observation_id=observation_id,
        target_requirement_id=requirement_id,
        capacity_commitment=1,
        estimated_cost_vector=(ResourceAmount("tokens", tokens),),
        requested_budget_vector=(ResourceAmount("tokens", tokens),),
        expected_completion_window=(
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        duplication_tolerance=0,
        communication_needs=(),
    )
    return BidCandidate(
        bid=bid,
        intent=intent,
        observation=observation,
        exploration_eligible=exploration,
    )


def _single_policy() -> AdmissionPolicy:
    return AdmissionPolicy(
        schema_version=1,
        policy_version="admission-v1",
        action_tool_policies=(
            ActionToolPolicy("fixture_lookup", ("fixture.read",)),
        ),
        blocked_risk_flags=("hard-stop",),
    )


def _policy(**overrides: object) -> MultiAdmissionPolicy:
    values: dict[str, object] = {
        "schema_version": 1,
        "policy_version": "multi-admission-v1",
        "max_concurrent_commitments": 2,
        "max_commitments_per_requirement": 2,
        "exploration_min_slots": 0,
        "tie_break_rule": "bid_id_lexicographic",
    }
    values.update(overrides)
    return MultiAdmissionPolicy(**values)


def _resolve(candidates, **overrides: object):
    values: dict[str, object] = {
        "candidates": tuple(candidates),
        "run_budget": (ResourceAmount("tokens", 100),),
        "reserved_resources": (),
        "existing_requirement_loads": (),
        "ready_requirement_ids": ("sources", "answer"),
        "current_concurrency": 0,
        "admission_policy": _single_policy(),
        "policy": _policy(),
        "at": "2026-07-30T09:00:30+08:00",
        "run_finalized": False,
    }
    values.update(overrides)
    return resolve_multi_admission(**values)


def test_candidate_order_permutations_produce_identical_result_and_tie_break() -> None:
    candidates = (
        _candidate("bid-b", "agent-b", tokens=60),
        _candidate("bid-a", "agent-a", tokens=60),
    )
    results = [
        _resolve(order, policy=_policy(max_concurrent_commitments=1))
        for order in permutations(candidates)
    ]

    assert results[0] == results[1]
    assert results[0].to_json() == results[1].to_json()
    assert MultiAdmissionResult.from_dict(
        json.loads(results[0].to_json())
    ) == results[0]
    assert results[0].admitted_bid_ids == ("bid-a",)
    assert results[0].decision_for("bid-b").reason is (
        MultiAdmissionReason.CONCURRENCY_LIMIT
    )


def test_resource_and_existing_concurrency_limits_fail_closed() -> None:
    candidates = (
        _candidate("bid-a", "agent-a", tokens=60),
        _candidate("bid-b", "agent-b", tokens=50),
    )
    resource_limited = _resolve(candidates)
    assert resource_limited.admitted_bid_ids == ("bid-a",)
    assert resource_limited.decision_for("bid-b").reason is (
        MultiAdmissionReason.BUDGET_LIMIT
    )

    concurrency_limited = _resolve(
        candidates,
        current_concurrency=2,
    )
    assert concurrency_limited.admitted_bid_ids == ()
    assert all(
        item.reason is MultiAdmissionReason.CONCURRENCY_LIMIT
        for item in concurrency_limited.decisions
    )


def test_duplicate_threshold_counts_existing_and_new_commitments() -> None:
    result = _resolve(
        (
            _candidate("bid-a", "agent-a"),
            _candidate("bid-b", "agent-b"),
        ),
        existing_requirement_loads=(RequirementLoad("sources", 1),),
        policy=_policy(max_commitments_per_requirement=1),
    )

    assert result.admitted_bid_ids == ()
    assert all(
        item.reason is MultiAdmissionReason.DUPLICATE_LIMIT
        for item in result.decisions
    )


def test_requirement_must_be_explicitly_dependency_ready() -> None:
    result = _resolve(
        (_candidate("bid-a", "agent-a", requirement_id="answer"),),
        ready_requirement_ids=("sources",),
    )

    assert result.admitted_bid_ids == ()
    assert result.decision_for("bid-a").reason is (
        MultiAdmissionReason.DEPENDENCY_NOT_READY
    )


def test_explicit_exploration_quota_is_applied_before_stable_tie_break() -> None:
    result = _resolve(
        (
            _candidate("bid-a", "agent-a"),
            _candidate("bid-z", "agent-z", exploration=True),
        ),
        policy=_policy(
            max_concurrent_commitments=1,
            exploration_min_slots=1,
        ),
    )

    assert result.admitted_bid_ids == ("bid-z",)
    assert result.exploration_quota_met is True
    assert result.decision_for("bid-z").status is MultiAdmissionStatus.ADMITTED


def test_risk_hard_stop_and_finalization_reject_whole_batch_without_commitments() -> None:
    candidates = (
        _candidate("bid-a", "agent-a"),
        _candidate(
            "bid-b",
            "agent-b",
            risk_flags=("hard-stop",),
        ),
    )
    risk = _resolve(candidates)
    assert risk.admitted_bid_ids == ()
    assert all(
        item.reason is MultiAdmissionReason.RISK_HARD_STOP
        for item in risk.decisions
    )

    finalized = _resolve(candidates[:1], run_finalized=True)
    assert finalized.admitted_bid_ids == ()
    assert finalized.decision_for("bid-a").reason is (
        MultiAdmissionReason.RUN_FINALIZED
    )


def test_invalid_parent_is_rejected_without_affecting_valid_candidate() -> None:
    invalid = _candidate(
        "bid-a",
        "agent-a",
        intent_id="intent-valid",
    )
    invalid_bid = AgentBid(
        **{
            **invalid.bid.__dict__,
            "intent_id": "intent-other",
        }
    )
    invalid = BidCandidate(
        bid=invalid_bid,
        intent=invalid.intent,
        observation=invalid.observation,
        exploration_eligible=False,
    )
    result = _resolve((invalid, _candidate("bid-b", "agent-b")))

    assert result.admitted_bid_ids == ("bid-b",)
    assert result.decision_for("bid-a").reason is MultiAdmissionReason.INVALID_BID
