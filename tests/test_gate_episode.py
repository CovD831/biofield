from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.contracts import (
    CommitmentStatus,
    RequirementStatus,
    ResourceAmount,
)
from biofield.gate_episode import (
    PrivateAgentState,
    derive_scripted_behavior,
    replay_gate_episode,
    run_gate_episode,
    shared_field_observation,
)
from biofield.local_runtime import HarnessCycleError


def _states():
    return {
        "agent-a": PrivateAgentState(
            state_version=0,
            collect_capability=0.9,
            verify_capability=0.2,
            caution=0.1,
            consumed_evidence_refs=(),
        ),
        "agent-b": PrivateAgentState(
            state_version=0,
            collect_capability=0.2,
            verify_capability=0.9,
            caution=0.1,
            consumed_evidence_refs=(),
        ),
        "agent-c": PrivateAgentState(
            state_version=0,
            collect_capability=0.3,
            verify_capability=0.3,
            caution=0.95,
            consumed_evidence_refs=(),
        ),
    }


def _run(states=None):
    return run_gate_episode(
        run_id="gate-episode-1",
        private_states=_states() if states is None else states,
        run_budget=(ResourceAmount("tokens", 100),),
        initial_at="2026-07-30T10:00:30+08:00",
        refused_at="2026-07-30T10:00:40+08:00",
        takeover_at="2026-07-30T10:01:00+08:00",
        requested_at="2026-07-30T10:01:10+08:00",
        delivered_at="2026-07-30T10:01:20+08:00",
        received_at="2026-07-30T10:01:21+08:00",
        consumed_at="2026-07-30T10:01:22+08:00",
        followup_at="2026-07-30T10:01:30+08:00",
        finished_at="2026-07-30T10:01:50+08:00",
    )


def _replay(events, states=None):
    return replay_gate_episode(
        run_id="gate-episode-1",
        private_states=_states() if states is None else states,
        run_budget=(ResourceAmount("tokens", 100),),
        initial_at="2026-07-30T10:00:30+08:00",
        refused_at="2026-07-30T10:00:40+08:00",
        takeover_at="2026-07-30T10:01:00+08:00",
        requested_at="2026-07-30T10:01:10+08:00",
        delivered_at="2026-07-30T10:01:20+08:00",
        received_at="2026-07-30T10:01:21+08:00",
        consumed_at="2026-07-30T10:01:22+08:00",
        followup_at="2026-07-30T10:01:30+08:00",
        finished_at="2026-07-30T10:01:50+08:00",
        events=tuple(events),
    )


def _rehash(event, payload):
    return replace(
        event,
        payload=payload,
        payload_sha256=hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    )


def test_private_state_not_identity_determines_behavior_and_swaps_cleanly():
    states = _states()
    observations = {
        agent: shared_field_observation(agent)
        for agent in sorted(states)
    }
    baseline = {
        agent: derive_scripted_behavior(
            agent_id=agent,
            observation=observations[agent],
            private_state=state,
        ).behavior_kind
        for agent, state in states.items()
    }
    assert baseline == {
        "agent-a": "collect",
        "agent-b": "request_evidence",
        "agent-c": "refuse",
    }

    swapped = dict(states)
    swapped["agent-a"], swapped["agent-b"] = (
        states["agent-b"],
        states["agent-a"],
    )
    assert derive_scripted_behavior(
        agent_id="agent-a",
        observation=observations["agent-a"],
        private_state=swapped["agent-a"],
    ).behavior_kind == baseline["agent-b"]
    assert derive_scripted_behavior(
        agent_id="agent-b",
        observation=observations["agent-b"],
        private_state=swapped["agent-b"],
    ).behavior_kind == baseline["agent-a"]

    renamed = derive_scripted_behavior(
        agent_id="renamed-agent",
        observation=shared_field_observation("renamed-agent"),
        private_state=states["agent-a"],
    )
    assert renamed.behavior_kind == baseline["agent-a"]
    assert renamed.intent.proposed_action_family == "source.collect"


def test_unified_episode_refusal_communication_changes_behavior_and_completes():
    result = _run()

    assert result.initial_behaviors == {
        "agent-a": "collect",
        "agent-b": "request_evidence",
        "agent-c": "refuse",
    }
    assert result.refusal.agent_id == "agent-c"
    assert result.takeover_commitment.agent_id == "agent-b"
    assert result.before_communication.behavior_kind == "request_evidence"
    assert result.after_communication.behavior_kind == "verify_evidence"
    assert (
        result.after_communication.intent.dependency_refs
        == (result.communication_consumption.consumption_id,)
    )
    assert result.followup_commitment.agent_id == "agent-b"
    assert result.action.input_refs[0] == result.followup_commitment.commitment_id
    assert result.residual.requirement(
        "sources"
    ).status is RequirementStatus.SATISFIED
    assert tuple(item.status for item in result.lifecycles) == (
        CommitmentStatus.CANCELLED,
        CommitmentStatus.COMPLETED,
    )
    assert result.ledger_totals["tokens"]["spent"] == "23"
    assert result.ledger_totals["tokens"]["shared_pool"] == "77"
    assert result.organization_snapshot.central_preset_info.role_bindings == ()
    assert result.organization_snapshot.central_preset_info.route_refs == ()
    assert result.organization_snapshot.central_preset_info.topology_refs == ()
    assert _replay(result.events).terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_consumption_is_required_and_cannot_be_forged_to_claim_behavior_change():
    result = _run()
    consumption_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "gate_communication_consumption"
    )
    without_consumption = tuple(
        replace(event, public_state_revision=index)
        for index, event in enumerate(
            (
                *result.events[:consumption_index],
                *result.events[consumption_index + 1 :],
            )
        )
    )
    with pytest.raises(HarnessCycleError, match="consumption"):
        _replay(without_consumption)

    consumption = result.events[consumption_index]
    payload = consumption.to_dict()["payload"]
    payload["consumption"]["consumer_agent_id"] = "agent-a"
    forged = _rehash(consumption, payload)
    with pytest.raises(HarnessCycleError, match="consumption"):
        _replay(
            (
                *result.events[:consumption_index],
                forged,
                *result.events[consumption_index + 1 :],
            )
        )


def test_public_episode_never_leaks_private_values_or_hidden_utility():
    result = _run()
    encoded = json.dumps(
        [event.to_dict() for event in result.events],
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    for private_name in (
        "collect_capability",
        "verify_capability",
        "caution",
        "consumed_evidence_refs",
        "hidden_utility",
    ):
        assert private_name not in encoded
    assert '"values"' not in encoded
    state_events = tuple(
        event
        for event in result.events
        if event.event_type.startswith("local_state_")
    )
    assert state_events
    assert all(event.payload["audience"] == "public" for event in state_events)
    assert all(
        event.payload["redaction"] == "private_values_omitted"
        for event in state_events
    )
