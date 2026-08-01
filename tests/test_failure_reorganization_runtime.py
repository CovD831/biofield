from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.contracts import ActionStatus, CommitmentStatus, ResourceAmount
from biofield.failure_runtime import (
    ScriptedFailureExecution,
    replay_failure_reorganization,
    run_failure_reorganization,
)
from biofield.local_runtime import HarnessCycleError
from test_refusal_takeover_runtime import _inputs


def _execution(agent: str, status: ActionStatus, cost: int, minute: int):
    return ScriptedFailureExecution(
        execution_id=f"execution-{agent}",
        agent_id=agent,
        requested_resources=(ResourceAmount("tokens", 30),),
        actual_cost=(ResourceAmount("tokens", cost),),
        status=status,
        started_at=f"2026-07-30T09:0{minute}:10+08:00",
        finished_at=f"2026-07-30T09:0{minute}:20+08:00",
    )


def _run():
    candidates, admission, multi, _ = _inputs()
    return run_failure_reorganization(
        run_id="failure-run-1",
        candidates=candidates,
        admission_policy=admission,
        multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        initial_at="2026-07-30T09:00:30+08:00",
        initial_execution=_execution("a", ActionStatus.FAILED, 10, 1),
        readmission_at="2026-07-30T09:02:00+08:00",
        takeover_execution=_execution("b", ActionStatus.SUCCEEDED, 20, 3),
    )


def _replay(events):
    candidates, admission, multi, _ = _inputs()
    return replay_failure_reorganization(
        candidates=candidates,
        admission_policy=admission,
        multi_policy=multi,
        run_budget=(ResourceAmount("tokens", 100),),
        events=events,
    )


def _rehash(event, payload):
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return replace(event, payload=payload, payload_sha256=digest)


def test_failure_settles_then_publicly_readmits_and_completes_takeover():
    result = _run()
    assert result.initial_selection.admitted_bid_ids == ("bid-a",)
    assert result.readmission.admitted_bid_ids == ("bid-b",)
    assert tuple(item.status for item in result.lifecycles) == (
        CommitmentStatus.CANCELLED,
        CommitmentStatus.COMPLETED,
    )
    assert result.ledger_totals["tokens"]["spent"] == "30"
    assert result.ledger_totals["tokens"]["shared_pool"] == "70"
    assert result.ledger_totals["tokens"]["escrow"] == "0"
    assert result.ledger_totals["tokens"]["reserved"] == "0"
    assert len(result.organization_snapshot.requirement_commitments) == 2
    assert result.organization_snapshot.central_preset_info.role_bindings == ()
    assert _replay(result.events).terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_failure_parent_settlement_barrier_and_double_execution_fail_closed():
    result = _run()
    failure_index = next(
        i for i, event in enumerate(result.events)
        if event.event_type == "failure_execution"
    )
    forged_failure = replace(
        result.events[failure_index],
        causal_parent_ids=(result.events[0].event_id,),
    )
    with pytest.raises(HarnessCycleError, match="failure parent"):
        _replay(
            (
                *result.events[:failure_index],
                forged_failure,
                *result.events[failure_index + 1 :],
            )
        )

    readmission_index = next(
        i for i, event in enumerate(result.events)
        if event.event_type == "failure_readmission"
    )
    transition = next(
        event for event in result.events
        if event.event_type == "failure_commitment_transition"
    )
    no_settlement_barrier = replace(
        result.events[readmission_index],
        causal_parent_ids=(transition.event_id,),
    )
    with pytest.raises(HarnessCycleError, match="settlement barrier"):
        _replay(
            (
                *result.events[:readmission_index],
                no_settlement_barrier,
                *result.events[readmission_index + 1 :],
            )
        )

    executions = tuple(
        (i, event) for i, event in enumerate(result.events)
        if event.event_type in {"failure_execution", "takeover_execution"}
    )
    second_index, second = executions[1]
    payload = second.to_dict()["payload"]
    payload["execution"]["commitment_id"] = executions[0][1].payload[
        "execution"
    ]["commitment_id"]
    duplicate = _rehash(second, payload)
    with pytest.raises(HarnessCycleError, match="double execution"):
        _replay(
            (
                *result.events[:second_index],
                duplicate,
                *result.events[second_index + 1 :],
            )
        )


def test_failed_agent_cannot_be_immediately_reselected_by_tampering():
    result = _run()
    index = next(
        i for i, event in enumerate(result.events)
        if event.event_type == "failure_readmission"
    )
    payload = result.events[index].to_dict()["payload"]
    payload["candidate_bid_ids"] = ("bid-a", "bid-b", "bid-c")
    forged = _rehash(result.events[index], payload)
    with pytest.raises(HarnessCycleError, match="failed Agent"):
        _replay((*result.events[:index], forged, *result.events[index + 1 :]))
