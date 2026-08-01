from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.admission import ActionToolPolicy, AdmissionPolicy
from biofield.contracts import (
    AgentBid,
    AgentIntent,
    AgentRefusal,
    LocalFieldObservation,
    RefusalReason,
    ResourceAmount,
)
from biofield.local_runtime import HarnessCycleError
from biofield.multi_admission import BidCandidate, MultiAdmissionPolicy
from biofield.refusal_runtime import replay_refusal_takeover, run_refusal_takeover


def _candidate(agent: str, bid_id: str) -> BidCandidate:
    observation = LocalFieldObservation(
        schema_version=1, observation_id=f"obs-{agent}", agent_id=agent,
        task_id="task-1", requirement_schema_version=1, public_state_revision=0,
        visible_requirement_signals=("sources",), congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 100),), risk_flags=(),
        source_event_ids=("task-start",), field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:10:00+08:00",
    )
    intent = AgentIntent(
        schema_version=1, intent_id=f"intent-{agent}", agent_id=agent,
        observation_id=observation.observation_id, local_state_version=0,
        target_requirement_id="sources", proposed_action_family="lookup",
        expected_evidence_type="source", expected_marginal_progress=.5,
        confidence=.5, uncertainty=.5,
        requested_resource_bounds=(ResourceAmount("tokens", 40),),
        dependency_refs=(), expires_at="2026-07-30T09:09:00+08:00",
    )
    bid = AgentBid(
        schema_version=1, bid_id=bid_id, agent_id=agent,
        intent_id=intent.intent_id, observation_id=observation.observation_id,
        target_requirement_id="sources", capacity_commitment=1,
        estimated_cost_vector=(ResourceAmount("tokens", 30),),
        requested_budget_vector=(ResourceAmount("tokens", 40),),
        expected_completion_window=("2026-07-30T09:01:00+08:00",
                                    "2026-07-30T09:08:00+08:00"),
        duplication_tolerance=0, communication_needs=(),
    )
    return BidCandidate(bid=bid, intent=intent, observation=observation,
                        exploration_eligible=False)


def _inputs():
    candidates = (_candidate("a", "bid-a"), _candidate("b", "bid-b"),
                  _candidate("c", "bid-c"))
    admission = AdmissionPolicy(
        schema_version=1, policy_version="admission-v1",
        action_tool_policies=(ActionToolPolicy("lookup", ("fixture.read",)),),
    )
    multi = MultiAdmissionPolicy(
        schema_version=1, policy_version="multi-v1",
        max_concurrent_commitments=1, max_commitments_per_requirement=1,
        exploration_min_slots=0, tie_break_rule="bid_id_lexicographic",
    )
    refusal = AgentRefusal(
        schema_version=1, refusal_id="refusal-a", agent_id="a",
        observation_id="obs-a", local_state_version=0,
        target_requirement_id="sources",
        reason_code=RefusalReason.INSUFFICIENT_CAPABILITY,
        bounded_explanation="cannot verify", retry_conditions=(
            "retry_not_before=2026-07-30T09:01:00+08:00",
            "retry_expires_at=2026-07-30T09:03:00+08:00",
        ),
    )
    return candidates, admission, multi, refusal


def test_refusal_takes_no_resources_and_next_public_bid_gets_commitment():
    candidates, admission, multi, refusal = _inputs()
    result = run_refusal_takeover(
        run_id="run-r1", candidates=candidates, refusal=refusal,
        admission_policy=admission, multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        initial_at="2026-07-30T09:00:30+08:00",
        refused_at="2026-07-30T09:00:50+08:00",
        readmission_at="2026-07-30T09:01:30+08:00",
    )
    assert result.initial_selection.admitted_bid_ids == ("bid-a",)
    assert result.readmission.admitted_bid_ids == ("bid-b",)
    assert result.commitment.agent_id == "b"
    assert result.ledger_totals["tokens"]["escrow"] == "40"
    assert not any("AgentEscrow[a]" in event.to_json() for event in result.events)
    assert result.organization_snapshot.refusal_distribution[0].count == 1
    assert result.organization_snapshot.central_preset_info.role_bindings == ()
    assert replay_refusal_takeover(
        candidates=candidates, admission_policy=admission, multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),), events=result.events,
    ).terminal_projection_sha256 == result.terminal_projection_sha256


def test_expired_retry_and_forged_takeover_parent_fail_closed():
    candidates, admission, multi, refusal = _inputs()
    kwargs = dict(run_id="run-r1", candidates=candidates, refusal=refusal,
                  admission_policy=admission, multi_policy=multi,
                  run_budget=(ResourceAmount("tokens", 100),),
                  initial_at="2026-07-30T09:00:30+08:00",
                  refused_at="2026-07-30T09:00:50+08:00")
    with pytest.raises(HarnessCycleError, match="retry condition expired"):
        run_refusal_takeover(**kwargs,
                             readmission_at="2026-07-30T09:03:00+08:00")
    result = run_refusal_takeover(**kwargs,
                                  readmission_at="2026-07-30T09:01:30+08:00")
    index = next(i for i, event in enumerate(result.events)
                 if event.event_type == "refusal_readmission")
    forged = replace(result.events[index],
                     causal_parent_ids=(result.events[0].event_id,))
    events = (*result.events[:index], forged, *result.events[index + 1:])
    with pytest.raises(HarnessCycleError, match="takeover parent"):
        replay_refusal_takeover(
            candidates=candidates, admission_policy=admission,
            multi_policy=multi, run_budget=(ResourceAmount("tokens", 100),),
            events=events,
        )
